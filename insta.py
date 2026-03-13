import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
import random
import time
import re

# =====================================
# BOT CONFIG
# =====================================

TOKEN = "8780791852:AAHqVZYRVc7QEyzCNxzAqIdfDCZuoMPZtYY"

bot = telebot.TeleBot(TOKEN)

post_cache = {}
user_last_request = {}

COOLDOWN = 10

# =====================================
# SESSION
# =====================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "X-IG-App-ID": "936619743392459",
    "Accept-Language": "en-US,en;q=0.9"
})

# =====================================
# DOWNLOAD PROXIES
# =====================================

def fetch_proxies():

    url = "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc"

    try:

        r = requests.get(url, timeout=20)

        data = r.json()

        proxies = []

        for proxy in data["data"]:

            ip = proxy["ip"]
            port = proxy["port"]

            proxies.append(f"http://{ip}:{port}")

        return proxies

    except:

        return []

# =====================================
# TEST PROXY
# =====================================

def test_proxy(proxy):

    try:

        r = requests.get(
            "https://api.ipify.org",
            proxies={"http": proxy, "https": proxy},
            timeout=5
        )

        if r.status_code == 200:
            return True

    except:
        pass

    return False

# =====================================
# BUILD WORKING PROXY POOL
# =====================================

def build_proxy_pool():

    raw = fetch_proxies()

    working = []

    print("Testing proxies...")

    for proxy in raw:

        if test_proxy(proxy):

            print("Working proxy:", proxy)

            working.append(proxy)

        if len(working) >= 20:
            break

    return working

proxy_list = build_proxy_pool()

# =====================================
# GET RANDOM PROXY
# =====================================

def get_proxy():

    global proxy_list

    if not proxy_list:

        proxy_list = build_proxy_pool()

    proxy = random.choice(proxy_list)

    return {
        "http": proxy,
        "https": proxy
    }

# =====================================
# USERNAME EXTRACTION
# =====================================

def extract_username(text):

    text = text.strip()

    match = re.search(r"instagram\.com/([A-Za-z0-9_.]+)", text)

    if match:
        return match.group(1)

    return text

# =====================================
# FETCH INSTAGRAM PROFILE
# =====================================

def fetch_profile(username):

    url = "https://i.instagram.com/api/v1/users/web_profile_info/"

    params = {"username": username.lower()}

    # ---- TRY WITH PROXIES ----

    for attempt in range(8):

        proxy = get_proxy()

        try:

            delay = random.uniform(2,5)
            print("Delay:", delay)

            time.sleep(delay)

            r = session.get(
                url,
                params=params,
                proxies=proxy,
                timeout=15
            )

            print("Proxy used:", proxy)
            print("Status:", r.status_code)

            if r.status_code == 200:

                data = r.json()

                return data["data"]["user"]["edge_owner_to_timeline_media"]

        except Exception as e:

            print("Proxy failed:", e)

    # ---- FALLBACK WITHOUT PROXY ----

    print("All proxies failed. Trying direct connection...")

    try:

        r = session.get(
            url,
            params=params,
            timeout=15
        )

        if r.status_code == 200:

            data = r.json()

            return data["data"]["user"]["edge_owner_to_timeline_media"]

    except Exception as e:

        print("Direct request failed:", e)

    return None

# =====================================
# START COMMAND
# =====================================

@bot.message_handler(commands=['start'])
def start(message):

    bot.send_message(
        message.chat.id,
        "📸 Instagram Downloader\n\nSend an Instagram username or profile link."
    )

# =====================================
# PROFILE HANDLER
# =====================================

@bot.message_handler(func=lambda m: True)
def profile_handler(message):

    username = extract_username(message.text)

    data = fetch_profile(username)

    if not data:

        bot.send_message(message.chat.id, "❌ Profile not found or connection failed.")
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

# =====================================
# BUTTON HANDLER
# =====================================

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

# =====================================
# NEXT BUTTON
# =====================================

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

# =====================================
# RUN BOT
# =====================================

bot.remove_webhook()

time.sleep(1)

bot.infinity_polling(
    timeout=30,
    long_polling_timeout=30
)
