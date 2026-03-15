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

TOKEN = "8755937047:AAHBFaKCan-W8QLls2DDJ3-XpUdyw3tP16w"
bot = telebot.TeleBot(TOKEN, threaded=True)
from queue import Queue
user_jobs ={}
job_queue = Queue()
# =========================
# INSTAGRAM SESSION
# =========================

# IG_SESSIONID = "80454330558%3AgyVmoDRy4c8pBj%3A10%3AAYiQ7rgvA8jCZ_WEFR54X9TEPmj2mRs1s_cM8Mfghg"

# =========================
# JOB SYSTEM

# =========================
# LOG FUNCTION
# =========================
def load_instaloader_cookies(loader):

    with open("cookies.txt", "r") as f:

        for line in f:

            if line.startswith("#"):
                continue

            parts = line.strip().split("\t")

            if len(parts) < 7:
                continue

            domain = parts[0]
            path = parts[2]
            name = parts[5]
            value = parts[6]

            loader.context._session.cookies.set(
                name,
                value,
                domain=domain,
                path=path
            )

    log("Instaloader cookies loaded")

def detect_instagram_state(page):

    url = page.url
    title = page.title()

    try:
        body = page.inner_text("body")
    except:
        body = ""

    log(f"Page URL: {url}")
    log(f"Page title: {title}")

    # LOGIN WALL
    if "accounts/login" in url:
        return "LOGIN_REQUIRED"

    # SESSION EXPIRED
    if "Please log in" in body:
        return "SESSION_EXPIRED"

    # CHALLENGE / CHECKPOINT
    if "challenge" in url or "checkpoint" in url:
        return "CHALLENGE"

    # RATE LIMIT
    if "Try again later" in body or "Please wait a few minutes" in body:
        return "RATE_LIMIT"

    # PROFILE NOT FOUND
    if "Sorry, this page isn't available" in body:
        return "PROFILE_NOT_FOUND"

    # EMPTY PAGE / SELECTOR MISSING
    if page.query_selector("article a") is None:
        return "EMPTY_PAGE"

    return "OK"
def log(msg):
    t = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{t}] {msg}")
    
# SESSION FUNCTION
def load_cookies(context):

    cookies = []

    with open("cookies.txt", "r") as f:
        for line in f:

            if line.startswith("#"):
                continue

            parts = line.strip().split("\t")

            if len(parts) < 7:
                continue
  
            cookies.append({
                "domain": parts[0],
                "path": parts[2],
                "name": parts[5],
                "value": parts[6],
                "secure": True,
                "httpOnly": False
            })

    context.add_cookies(cookies)
import os
print("Files in project:", os.listdir())

# =========================
# INSTALOADER
# =========================

L = instaloader.Instaloader(
    download_pictures=False,
    download_videos=False,
    download_video_thumbnails=False,
    save_metadata=False
)
L.context.request_timeout = 60
L.context.max_connection_attempts = 5
load_instaloader_cookies(L)

L.context._session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "X-IG-App-ID": "936619743392459",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.instagram.com/",
    "Accept": "*/*"
})
print("Instaloader session active")
# =========================
# START PLAYWRIGHT
# =========================

print("Starting browser...")

# def get_profile_posts(username, limit=100):

#     posts = []

#     profile = instaloader.Profile.from_username(
#         L.context,
#         username
#     )

#     for post in profile.get_posts():

#         posts.append(post)

#         if len(posts) >= limit:
#             break

#     log(f"Collected {len(posts)} posts using Instaloader")

#     return posts
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

    shortcode = post_url.rstrip("/").split("/")[-1]

    for attempt in range(5):

        try:
            log(f"Fetching shortcode: {shortcode}")

            post = instaloader.Post.from_shortcode(
                L.context,
                shortcode
            )

            return post

        except Exception as e:

            log(f"Instaloader retry {attempt+1}: {e}")

            time.sleep(random.uniform(10,20))

    return None
# =========================
# SCRAPER
# =========================

def scrape_background(job, context):
    username = job.username
    log(f"Scraping started for {username}")

    
    try:
        #create new page
        page = context.new_page()

        url = f"https://www.instagram.com/{username}/"

        for attempt in range(3):

            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_selector("header", timeout=20000)
                break

            except:
                log("Retry loading profile...")
                time.sleep(5)

        log("Main container loaded")

        # small scroll to trigger grid loading
        page.evaluate("window.scrollTo(0, 300)")
        time.sleep(2)

        # scroll again
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        state = detect_instagram_state(page)
        time.sleep(4)

        state = detect_instagram_state(page)
        if state == "EMPTY_PAGE":

            log("Page appears empty, performing progressive scroll")

            for i in range(3):

                page.evaluate("window.scrollBy(0, 600)")
                time.sleep(3)

                if page.query_selector("article") is not None:
                    log("Post grid detected after scroll")
                    break

            if page.query_selector("article") is None:
                log("Still empty after multiple scroll attempts")
                return

        if state != "OK":

            log(f"Instagram state detected: {state}")

            if state == "LOGIN_REQUIRED":
                log("Instagram forced login wall")

            elif state == "CHALLENGE":
                log("Instagram checkpoint challenge triggered")

            elif state == "RATE_LIMIT":
                log("Instagram soft block detected")

            elif state == "PROFILE_NOT_FOUND":
                log("Profile does not exist")

            page.close()
            return

        # wait for posts grid
        log("Waiting for post grid...")

        try:
            page.wait_for_selector("article a", timeout=30000)
        except:
            log("Grid not detected yet, scrolling to trigger loading")

            for i in range(5):

                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(4)

                if page.query_selector("article a") is not None:
                    log("Post grid detected after scroll")
                    break

            if page.query_selector("article a") is None:
                log("Still no posts found")
                return

        time.sleep(2)

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
        time.sleep(random.uniform(3,6))

        # trigger lazy loading
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(random.uniform(4,6))

        previous_height = 0

        previous_height = 0
        no_change_count = 0

        for _ in range(20):

            if not job.running:
                break

            # progressive human-like scroll
            page.evaluate("""
            window.scrollBy({
                top: 1200,
                left: 0,
                behavior: 'smooth'
            });
            """)

            time.sleep(random.uniform(3,5))

            log("Scanning page for posts...")

            links = page.evaluate("""
            Array.from(document.querySelectorAll('article a'))
            .map(a => "https://www.instagram.com" + a.getAttribute("href"))
            .filter(h => h.includes('/p/') || h.includes('/reel/'))
            """)

            new_posts = 0

            for link in links:

                link = link.split("?")[0]

                if link not in job.post_set:

                    job.posts.append(link)
                    job.post_set.add(link)
                    new_posts += 1

                    if len(job.posts) == 10:

                        markup = InlineKeyboardMarkup()

                        markup.add(
                            InlineKeyboardButton("Download 10 Posts", callback_data="next"),
                            InlineKeyboardButton("Cancel", callback_data="cancel")
                        )

                        bot.edit_message_text(
                            "✅ 10 posts collected.\nPress download to receive media.",
                            chat_id=job.chat_id,
                            message_id=job.message_id,
                            reply_markup=markup
                        )

            log(f"Collected posts: {len(job.posts)} (+{new_posts})")

            # detect if page stopped loading posts
            current_height = page.evaluate("document.body.scrollHeight")

            if current_height == previous_height:
                no_change_count += 1
            else:
                no_change_count = 0

            if no_change_count >= 3:
                log("No more posts loading")
                break

            previous_height = current_height

            log(f"Collected posts: {len(job.posts)} (+{new_posts})")
            previous_height = 0
            no_change_count = 0
            # detect if page stopped loading new posts
            current_height = page.evaluate("document.body.scrollHeight")

            if current_height == previous_height:
                no_change_count += 1
            else:
                no_change_count = 0

            if no_change_count >= 3:
                log("No more posts loading")
                break

            previous_height = current_height

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

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
            viewport={"width": 1280, "height": 900}
        )
        load_cookies(context)

        page = context.new_page()

        page.goto("https://www.instagram.com/accounts/edit/")
        print("Current URL:", page.url)
        print(context.cookies())

    #     context.add_cookies([
    #     {
    #         "name": "sessionid",
    #         "value": IG_SESSIONID,
    #         "domain": ".instagram.com",
    #         "path": "/",
    #         "httpOnly": True,
    #         "secure": True
    #     },
    #     {
    #         "name": "csrftoken",
    #         "value": "missing",
    #         "domain": ".instagram.com",
    #         "path": "/"
    #     }
    # ])

        page = context.new_page()

        page.goto("https://www.instagram.com/", wait_until="networkidle")

        time.sleep(5)

        log("Instagram session activated")
        while True:

            try:
                job = job_queue.get()
            except Exception as e:
                log(f"Queue error: {e}")
                continue

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
# JOB SYSTEM
# =========================

class Job:
    def __init__(self, username, chat_id, message_id=None):
        self.username = username
        self.chat_id = chat_id
        self.message_id = message_id
        self.posts = []
        self.post_set = set()
        self.sent = 0
        self.running = True

# =========================
# START COMMAND
# =========================

@bot.message_handler(commands=["start"])
def start(message):

    bot.send_message(
        message.chat.id,
        "Send Instagram username"
    )
# =========================
# USERNAME HANDLER
# =========================

@bot.message_handler(func=lambda m: True)
def profile_handler(message):

    username = message.text.strip().lower()

    msg = bot.send_message(
        message.chat.id,
        "⏳ Collecting media from profile..."
    )

    job = Job(username, message.chat.id, msg.message_id)
    user_jobs[message.chat.id] = job

    job_queue.put(job)

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

        log(f"Processing post URL: {post_url}")
        time.sleep(random.uniform(6,12))
        post = get_post_from_url(post_url)

        if not post:
            bot.send_message(call.message.chat.id, post_url)
            continue

        medias = extract_media(post)

        for media_type, media_url in medias:

            log(f"Checking post: {post.shortcode}")
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

    # cooldown every 10 posts to avoid Instagram rate limits
    if job.sent % 10 == 0:
        log("Cooldown triggered to avoid rate limit")
        time.sleep(random.uniform(6,10))

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
