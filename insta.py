import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
import re
import json
import time
import random
time.sleep(random.uniform(2,4))
TOKEN = "8755937047:AAHBFaKCan-W8QLls2DDJ3-XpUdyw3tP16w"

bot = telebot.TeleBot(TOKEN)

post_cache = {}

user_last_request = {}
COOLDOWN = 10
def extract_username(text):

    text = text.strip()

    match = re.search(r"instagram\.com/([A-Za-z0-9_.]+)", text)

    if match:
        return match.group(1)

    return text
def fetch_profile(username):

    import random
    time.sleep(random.uniform(2,4))

    url = "https://i.instagram.com/api/v1/users/web_profile_info/"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "X-IG-App-ID": "936619743392459"
    }

    params = {
        "username": username
    }

    proxies = {
        "http": "http://Netherlands:NL@94.176.3.43:7443",
        "http": "http://Netherlands:NL@94.176.3.43:7443"
    }

    r = requests.get(url, headers=headers, params=params, proxies=proxies)

    print("Status:", r.status_code)

    if r.status_code != 200:
        return None

    return r.json()
@bot.message_handler(commands=['start'])
def start(message):

    bot.send_message(
        message.chat.id,
        "📸 Instagram Downloader\n\nSend an Instagram username."
    )
@bot.message_handler(func=lambda m: True)
def profile_handler(message):

    username = extract_username(message.text)

    data = fetch_profile(username)

    if not data:
        bot.send_message(message.chat.id, "Profile not found")
        return

    user = data["entry_data"]["ProfilePage"][0]["graphql"]["user"]

    followers = user["edge_followed_by"]["count"]
    following = user["edge_follow"]["count"]
    posts = user["edge_owner_to_timeline_media"]["count"]

    profile_pic = user["profile_pic_url_hd"]
    bio = user["biography"]

    text = f"""
📸 Instagram Profile

👤 Username: {username}

👥 Followers: {followers}
➡ Following: {following}
📦 Posts: {posts}

📄 Bio:
{bio}
"""

    markup = InlineKeyboardMarkup()

    btn = InlineKeyboardButton(
        "Download Posts",
        callback_data=f"posts|{username}|0"
    )

    markup.add(btn)

    bot.send_photo(
        message.chat.id,
        profile_pic,
        caption=text,
        reply_markup=markup
    )
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):

    action, username, start = call.data.split("|")
    start = int(start)

    if username not in post_cache:

        data = fetch_profile_html(username)

        if not data:
            bot.send_message(call.message.chat.id, "Profile not found")
            return

        user = data["entry_data"]["ProfilePage"][0]["graphql"]["user"]

        edges = user["edge_owner_to_timeline_media"]["edges"]

        post_cache[username] = edges

    edges = post_cache[username]

    posts = edges[start:start+10]

    for post in posts:

        node = post["node"]

        if node["is_video"]:
            bot.send_video(call.message.chat.id, node["video_url"])
        else:
            bot.send_photo(call.message.chat.id, node["display_url"])
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
print("cristianos profile - ") 
print(fetch_profile("cristiano"))
bot.infinity_polling()
        
        
        
        
        
        import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
import re
import json
import time
import random
time.sleep(random.uniform(2,4))
TOKEN = "8755937047:AAHBFaKCan-W8QLls2DDJ3-XpUdyw3tP16w"

bot = telebot.TeleBot(TOKEN)

post_cache = {}

user_last_request = {}
COOLDOWN = 10
def extract_username(text):

    text = text.strip()

    match = re.search(r"instagram\.com/([A-Za-z0-9_.]+)", text)

    if match:
        return match.group(1)

    return text
def fetch_profile(username):

    import random
    time.sleep(random.uniform(2,4))

    url = "https://i.instagram.com/api/v1/users/web_profile_info/"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "X-IG-App-ID": "936619743392459"
    }

    params = {
        "username": username
    }

    r = requests.get(url, headers=headers, params=params)

    print("Status:", r.status_code)

    if r.status_code != 200:
        return None

    try:
        return r.json()
    except:
        return None
@bot.message_handler(commands=['start'])
def start(message):

    bot.send_message(
        message.chat.id,
        "📸 Instagram Downloader\n\nSend an Instagram username."
    )
@bot.message_handler(func=lambda m: True)
def profile_handler(message):

    username = extract_username(message.text)

    data = fetch_profile(username)

    if not data:
        bot.send_message(message.chat.id, "Profile not found")
        return

    user = data["entry_data"]["ProfilePage"][0]["graphql"]["user"]

    followers = user["edge_followed_by"]["count"]
    following = user["edge_follow"]["count"]
    posts = user["edge_owner_to_timeline_media"]["count"]

    profile_pic = user["profile_pic_url_hd"]
    bio = user["biography"]

    text = f"""
📸 Instagram Profile

👤 Username: {username}

👥 Followers: {followers}
➡ Following: {following}
📦 Posts: {posts}

📄 Bio:
{bio}
"""

    markup = InlineKeyboardMarkup()

    btn = InlineKeyboardButton(
        "Download Posts",
        callback_data=f"posts|{username}|0"
    )

    markup.add(btn)

    bot.send_photo(
        message.chat.id,
        profile_pic,
        caption=text,
        reply_markup=markup
    )
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):

    action, username, start = call.data.split("|")
    start = int(start)

    if username not in post_cache:

        data = fetch_profile_html(username)

        if not data:
            bot.send_message(call.message.chat.id, "Profile not found")
            return

        user = data["entry_data"]["ProfilePage"][0]["graphql"]["user"]

        edges = user["edge_owner_to_timeline_media"]["edges"]

        post_cache[username] = edges

    edges = post_cache[username]

    posts = edges[start:start+10]

    for post in posts:

        node = post["node"]

        if node["is_video"]:
            bot.send_video(call.message.chat.id, node["video_url"])
        else:
            bot.send_photo(call.message.chat.id, node["display_url"])
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
print("cristianos profile - ") 
print(fetch_profile("cristiano"))
bot.infinity_polling()
        
        
        
        
        
        
