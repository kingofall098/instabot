import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
import time
import random
import re

# ==========================
# BOT CONFIG
# ==========================

TOKEN = "8756448611:AAHbnOlBbZP8639ZKHcFZd0vSQeK54EMSYQ"

bot = telebot.TeleBot(TOKEN)

post_cache = {}
user_last_request = {}

COOLDOWN = 10


# ==========================
# SESSION
# ==========================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9"
})

session.cookies.set("sessionid", "80484585414%3AD73TCLEIfkcHlo%3A18%3AAYiBvd2rYoe1v3CB-H7jy6iJxtU7kZMyoQsjFLOGBg")

# ==========================
# NETWORK CHECK
# ==========================

def internet_available():

    try:
        requests.get("https://api.ipify.org", timeout=5)
        return True
    except:
        return False


# ==========================
# USERNAME EXTRACTION
# ==========================

def extract_username(text):

    text = text.strip()

    match = re.search(r"instagram\.com/([A-Za-z0-9_.]+)", text)

    if match:
        return match.group(1)

    return text


# ==========================
# FETCH INSTAGRAM PROFILE
# ==========================


from playwright.sync_api import sync_playwright



def fetch_profile(username):

    from playwright.sync_api import sync_playwright
    import re
    import random
    import time

    with sync_playwright() as p:

        try:

            browser = p.chromium.launch(headless=True)
            context = browser.new_context()

            context.add_cookies([
                {
                    "name": "sessionid",
                    "value": "80484585414%3AD73TCLEIfkcHlo%3A18%3AAYgFHiooPrlXGxU7ndzIutGt94Ou_OigLOo0LIstlA",
                    "domain": ".instagram.com",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True
                }
            ])
            page = context.new_page()

            delay = random.uniform(5,8)
            print("Delay:", delay)
            time.sleep(delay)

            url = f"https://www.instagram.com/{username}/"
            print("Opening:", url)

            page.goto(url)

            # wait for page
            page.wait_for_timeout(5000)

            print("Page title:", page.title())
            print("Current URL:", page.url)

            html = page.content()

            print("HTML length:", len(html))

            # detect login wall
            if "login" in page.url.lower():
                print("Instagram redirected to login page")
                browser.close()
                return None

            # extract links
            links = re.findall(r'href="/(p|reel)/([^/]+)/"', html)

            print("Links found:", len(links))

            posts = []

            for post_type, code in links:

                if post_type == "reel":
                    media_url = f"https://www.instagram.com/reel/{code}/"
                else:
                    media_url = f"https://www.instagram.com/p/{code}/"

                posts.append({
                    "node": {
                        "is_video": False,
                        "display_url": media_url
                    }
                })

            browser.close()

            if not posts:
                print("No posts detected in HTML")
                print("First 500 chars of HTML:")
                print(html[:500])
                return None

            return {"edges": posts[:20]}

        except Exception as e:

            print("ERROR inside fetch_profile:", str(e))
            return None
# ==========================
# START COMMAND
# ==========================

@bot.message_handler(commands=['start'])
def start(message):

    bot.send_message(
        message.chat.id,
        "📸 Instagram Downloader\n\nSend username or profile link."
    )


# ==========================
# PROFILE HANDLER
# ==========================

@bot.message_handler(func=lambda m: True)
def profile_handler(message):

    username = extract_username(message.text)

    data = fetch_profile(username)

    if not data:

        bot.send_message(message.chat.id, "❌ Profile not found or network error.")
        return

    edges = data["edges"]

    post_cache[username] = edges

    markup = InlineKeyboardMarkup()

    btn = InlineKeyboardButton(
        "Download Posts",
        callback_data=f"posts|{username}|0"
    )

    markup.add(btn)

    bot.send_message(
        message.chat.id,
        f"Found {len(edges)} posts.",
        reply_markup=markup
    )


# ==========================
# BUTTON HANDLER
# ==========================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):

    user_id = call.from_user.id
    now = time.time()

    if user_id in user_last_request:

        elapsed = now - user_last_request[user_id]

        if elapsed < COOLDOWN:

            wait = int(COOLDOWN - elapsed)

            bot.answer_callback_query(
                call.id,
                f"Please wait {wait} seconds",
                show_alert=True
            )
            return

    user_last_request[user_id] = now

    action, username, start = call.data.split("|")

    start = int(start)

    edges = post_cache.get(username)

    if not edges:

        bot.send_message(call.message.chat.id, "Cache expired. Send username again.")
        return

    posts = edges[start:start+10]

    for post in posts:

        node = post["node"]

        if node["is_video"]:

            bot.send_video(call.message.chat.id, node["video_url"])

        else:

            bot.send_photo(call.message.chat.id, node["display_url"])


# ==========================
# PAGINATION
# ==========================

    next_start = start + 10

    if next_start < len(edges):

        markup = InlineKeyboardMarkup()

        btn = InlineKeyboardButton(
            "Next 10 Posts",
            callback_data=f"posts|{username}|{next_start}"
        )

        markup.add(btn)

        bot.send_message(
            call.message.chat.id,
            "Load more posts:",
            reply_markup=markup
        )

    else:

        bot.send_message(call.message.chat.id, "✅ No more posts.")


# ==========================
# RUN BOT
# ==========================

bot.remove_webhook()

time.sleep(1)

bot.infinity_polling(timeout=30, long_polling_timeout=30)
