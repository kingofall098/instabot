# ================================
# IMPORT LIBRARIES
# ================================
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import instaloader
import re
import time

# ================================
# BOT CONFIG
# ================================

TOKEN = "8628280617:AAEHHRQZ2dxsxoFWvmLs1PVO_wSCRn0rHPc"

bot = telebot.TeleBot(TOKEN)

# Instaloader (used to fetch instagram media)
loader = instaloader.Instaloader(
    download_pictures=False,
    download_videos=False,
    save_metadata=False
)

# ================================
# ANTI SPAM SYSTEM
# ================================

user_last_request = {}
COOLDOWN = 10  # seconds


# ================================
# USERNAME EXTRACTOR
# ================================
def extract_username(text):

    text = text.strip()

    match = re.search(r"instagram\.com/([A-Za-z0-9_.]+)", text)

    if match:
        return match.group(1)

    return text


# ================================
# START COMMAND
# ================================
@bot.message_handler(commands=['start'])
def start(message):

    bot.send_message(
        message.chat.id,
        "📸 Instagram Media Bot\n\nSend an Instagram username or profile link."
    )


# ================================
# USERNAME HANDLER
# ================================
@bot.message_handler(func=lambda m: True)
def handle_username(message):

    username = extract_username(message.text)

    try:

        profile = instaloader.Profile.from_username(loader.context, username)

        text = f"""
📸 Instagram Profile

👤 Username: {profile.username}
📝 Name: {profile.full_name}

👥 Followers: {profile.followers}
➡ Following: {profile.followees}
📦 Posts: {profile.mediacount}

📄 Bio:
{profile.biography}

Choose what you want to download:
"""

        # Buttons
        markup = InlineKeyboardMarkup()

        btn1 = InlineKeyboardButton("Latest Posts", callback_data=f"posts|{username}")
        btn2 = InlineKeyboardButton("Reels", callback_data=f"reels|{username}")
        btn3 = InlineKeyboardButton("Stories", callback_data=f"stories|{username}")
        btn4 = InlineKeyboardButton("Profile Picture", callback_data=f"dp|{username}")

        markup.row(btn1, btn2)
        markup.row(btn3, btn4)

        bot.send_photo(
            message.chat.id,
            profile.profile_pic_url,
            caption=text,
            reply_markup=markup
        )

    except:

        bot.send_message(
            message.chat.id,
            "❌ Username not found or account is private."
        )


# ================================
# BUTTON CALLBACK HANDLER
# ================================
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):

    user_id = call.from_user.id
    current_time = time.time()

    # Cooldown check
    if user_id in user_last_request:

        elapsed = current_time - user_last_request[user_id]

        if elapsed < COOLDOWN:

            remaining = int(COOLDOWN - elapsed)

            bot.answer_callback_query(
                call.id,
                f"⏳ Please wait {remaining} seconds.",
                show_alert=True
            )
            return

    user_last_request[user_id] = current_time

    action, username = call.data.split("|")

    # ================================
    # DOWNLOAD POSTS
    # ================================
    if action == "posts":

        bot.send_message(call.message.chat.id, f"Fetching posts from {username}...")

        try:

            profile = instaloader.Profile.from_username(loader.context, username)

            count = 0

            for post in profile.get_posts():

                bot.send_message(
                    call.message.chat.id,
                    f"Downloading post {count+1}/10..."
                )

                if post.is_video:
                    bot.send_video(call.message.chat.id, post.video_url)
                else:
                    bot.send_photo(call.message.chat.id, post.url)

                count += 1

                if count >= 10:
                    break

            bot.send_message(call.message.chat.id, "✅ Finished sending posts.")

        except:

            bot.send_message(call.message.chat.id, "❌ Error fetching posts.")


    # ================================
    # DOWNLOAD REELS
    # ================================
    elif action == "reels":

        bot.send_message(call.message.chat.id, f"Fetching reels from {username}...")

        try:

            profile = instaloader.Profile.from_username(loader.context, username)

            count = 0

            for post in profile.get_posts():

                if post.is_video:

                    bot.send_video(call.message.chat.id, post.video_url)

                    count += 1

                if count >= 10:
                    break

            if count == 0:
                bot.send_message(call.message.chat.id, "No reels found.")
            else:
                bot.send_message(call.message.chat.id, "✅ Finished sending reels.")

        except:

            bot.send_message(call.message.chat.id, "❌ Error fetching reels.")


    # ================================
    # DOWNLOAD STORIES
    # ================================
    elif action == "stories":

        bot.send_message(call.message.chat.id, "Fetching stories...")

        try:

            profile = instaloader.Profile.from_username(loader.context, username)

            user_id = profile.userid

            stories = loader.get_stories(userids=[user_id])

            found = False

            for story in stories:

                for item in story.get_items():

                    found = True

                    if item.is_video:
                        bot.send_video(call.message.chat.id, item.video_url)
                    else:
                        bot.send_photo(call.message.chat.id, item.url)

            if not found:
                bot.send_message(call.message.chat.id, "No active stories.")

        except:

            bot.send_message(call.message.chat.id, "❌ Stories require Instagram login.")


    # ================================
    # PROFILE PICTURE
    # ================================
    elif action == "dp":

        try:

            profile = instaloader.Profile.from_username(loader.context, username)

            bot.send_photo(
                call.message.chat.id,
                profile.profile_pic_url
            )

        except:

            bot.send_message(call.message.chat.id, "❌ Error fetching profile picture.")


# ================================
# RUN BOT
# ================================
bot.infinity_polling()
