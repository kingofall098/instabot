
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import instaloader
import time
import random
from http.cookiejar import MozillaCookieJar

TOKEN = "8780791852:AAHqVZYRVc7QEyzCNxzAqIdfDCZuoMPZtYY"
bot = telebot.TeleBot(TOKEN)

# -----------------------------
# INSTALOADER
# -----------------------------

L = instaloader.Instaloader(
    download_comments=False,
    save_metadata=False,
    download_video_thumbnails=False,
    rate_controller=lambda ctx: instaloader.RateController(ctx)
)

# -----------------------------
# LOAD COOKIE SESSION
# -----------------------------

def load_cookie_session():

    try:

        jar = MozillaCookieJar("cookies.txt")
        jar.load(ignore_discard=True, ignore_expires=True)

        for cookie in jar:
            L.context._session.cookies.set_cookie(cookie)

        print("Instagram cookies loaded")

    except Exception as e:
        print("Cookie loading failed:", e)


load_cookie_session()

# -----------------------------
# CACHE SYSTEM
# -----------------------------

user_cache = {}
profile_cache = {}

CACHE_TIME = 300

# -----------------------------
# delay system
# -----------------------------

def delay(a=5, b=8):
    time.sleep(random.uniform(a, b))

# -----------------------------
# get profile safely
# -----------------------------

def get_profile(username):

    now = time.time()

    if username in profile_cache:

        profile, timestamp = profile_cache[username]

        if now - timestamp < CACHE_TIME:
            return profile

    delay()

    profile = instaloader.Profile.from_username(L.context, username)

    profile_cache[username] = (profile, now)

    return profile

# -----------------------------
# start
# -----------------------------

@bot.message_handler(commands=['start'])
def start(message):

    bot.reply_to(
        message,
        "Send an Instagram username\nExample:\n\nnatgeo"
    )

# -----------------------------
# username handler
# -----------------------------

@bot.message_handler(func=lambda m: m.text and not m.text.startswith("/"))
def username_handler(message):

    username = message.text.strip().replace("@","")

    msg = bot.reply_to(message,"Fetching profile...")

    try:

        profile = get_profile(username)

    except Exception as e:

        if "429" in str(e):
            bot.edit_message_text(
                "⚠ Instagram rate limited the bot.\nPlease wait a few minutes.",
                message.chat.id,
                msg.message_id
            )
            return

        bot.edit_message_text(
            "Profile not found.",
            message.chat.id,
            msg.message_id
        )
        return

    user_cache[message.chat.id] = username

    text = f"""
Profile: {profile.username}
Followers: {profile.followers}
Posts: {profile.mediacount}

Choose what you want:
"""

    keyboard = InlineKeyboardMarkup()

    keyboard.add(
        InlineKeyboardButton("📸 Latest Posts", callback_data="posts")
    )

    keyboard.add(
        InlineKeyboardButton("🎥 Reels", callback_data="reels")
    )

    keyboard.add(
        InlineKeyboardButton("👤 Profile Info", callback_data="info")
    )

    bot.send_message(message.chat.id,text,reply_markup=keyboard)

# -----------------------------
# button handler
# -----------------------------

@bot.callback_query_handler(func=lambda call: True)
def callback(call):

    chat_id = call.message.chat.id

    if chat_id not in user_cache:

        bot.send_message(chat_id,"Send a username first.")
        return

    username = user_cache[chat_id]

    try:

        profile = get_profile(username)

    except Exception as e:

        bot.send_message(chat_id,"Instagram temporarily blocked requests.")
        return

    # latest posts
    if call.data == "posts":

        bot.send_message(chat_id,"Fetching latest posts...")

        count = 0

        for post in profile.get_posts():

            if count >= 10:
                break

            if post.is_video:
                bot.send_message(chat_id,post.video_url)
            else:
                bot.send_message(chat_id,post.url)

            count += 1

            delay(1,2)

    # reels
    elif call.data == "reels":

        bot.send_message(chat_id,"Fetching reels...")

        count = 0

        for post in profile.get_posts():

            if count >= 10:
                break

            if post.is_video:

                bot.send_message(chat_id,post.video_url)

                count += 1

                delay(1,2)

    # profile info
    elif call.data == "info":

        bio = profile.biography if profile.biography else "No bio"

        text = f"""
Username: {profile.username}
Followers: {profile.followers}
Following: {profile.followees}
Posts: {profile.mediacount}

Bio:
{bio}

Profile Pic:
{profile.profile_pic_url}
"""

        bot.send_message(chat_id,text)

# -----------------------------
# RUN BOT
# -----------------------------

print("Bot running...")

bot.remove_webhook()

bot.infinity_polling(skip_pending=True)
