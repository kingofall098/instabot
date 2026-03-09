import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import instaloader
import os
import re
import threading
# Dictionary to store last request time of each user
import time

user_last_request = {}

# Minimum seconds between requests
COOLDOWN = 10
TOKEN = "8628280617:AAEHHRQZ2dxsxoFWvmLs1PVO_wSCRn0rHPc"

bot = telebot.TeleBot(TOKEN)
loader = instaloader.Instaloader()

# Login to Instagram for story access
loader.login("your_username", "your_password")

# Function to extract Instagram username from text or link
def extract_username(text):

    text = text.strip()

    # If user sends full Instagram link
    match = re.search(r"instagram\.com/([A-Za-z0-9_.]+)", text)

    if match:
        return match.group(1)

    # Otherwise assume text itself is the username
    return text
# Start command
@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        "Welcome to Instagram Media Bot\n\nSend an Instagram username."
    )
# Function that downloads and sends latest posts
def download_posts(bot, chat_id, username):

    try:
        # Get Instagram profile
        profile = instaloader.Profile.from_username(loader.context, username)

        count = 0

        # Loop through posts
        for post in profile.get_posts():

            # Send progress message
            bot.send_message(chat_id, f"Downloading post {count+1}/10...")

            # Send video or photo
            if post.is_video:
                bot.send_video(chat_id, post.video_url)
            else:
                bot.send_photo(chat_id, post.url)

            count += 1

            # Stop at 10 posts
            if count >= 10:
                break

        bot.send_message(chat_id, "Finished sending latest posts.")

    except Exception:
        bot.send_message(chat_id, "Error fetching posts.")
# Username input
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):

    user_id = call.from_user.id
    current_time = time.time()

    # Check if user is on cooldown
    if user_id in user_last_request:
        elapsed = current_time - user_last_request[user_id]

        if elapsed < COOLDOWN:
            remaining = int(COOLDOWN - elapsed)
            bot.answer_callback_query(
                call.id,
                f"Please wait {remaining} seconds before another request.",
                show_alert=True
            )
            return

    # Update last request time
    user_last_request[user_id] = current_time

    # Get username from user message
    # Extract username from text or Instagram link
    username = extract_username(message.text)

    try:
        # Fetch Instagram profile data
        profile = instaloader.Profile.from_username(loader.context, username)

        # Build profile information text
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

        # Create inline keyboard buttons
        markup = InlineKeyboardMarkup()

        btn1 = InlineKeyboardButton("Latest Posts", callback_data=f"posts|{username}")
        btn2 = InlineKeyboardButton("Reels", callback_data=f"reels|{username}")
        btn3 = InlineKeyboardButton("Stories", callback_data=f"stories|{username}")
        btn4 = InlineKeyboardButton("Profile Picture", callback_data=f"dp|{username}")

        # Arrange buttons in rows
        markup.row(btn1, btn2)
        markup.row(btn3, btn4)

        # Send profile picture with caption and buttons
        bot.send_photo(
            message.chat.id,
            profile.profile_pic_url,
            caption=text,
            reply_markup=markup
        )

    except Exception as e:
        # Error if username invalid or private
        bot.send_message(
            message.chat.id,
            "❌ Username not found or profile is private."
        )
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):

    data = call.data
    action, username = data.split("|")

    if action == "posts":

        # Inform the user that the bot started fetching posts
        bot.send_message(call.message.chat.id, f"Fetching latest posts from {username}...")

        try:
            # Get the Instagram profile object
            profile = instaloader.Profile.from_username(loader.context, username)

            # Counter to limit posts to 10
            count = 0

            # Loop through posts of the profile
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

            # Notify user when finished
            bot.send_message(call.message.chat.id, "Finished sending latest posts.")

        except Exception as e:

            # Error handling if username doesn't exist or Instagram blocks request
            bot.send_message(
                call.message.chat.id,
                "Error fetching posts. The profile may be private or Instagram blocked the request."
            )

    elif action == "reels":

        # Tell the user that the bot started fetching reels
        bot.send_message(call.message.chat.id, f"Fetching latest reels from {username}...")

        try:
            # Get Instagram profile
            profile = instaloader.Profile.from_username(loader.context, username)

            # Counter to limit reels sent
            count = 0

            # Loop through profile posts
            for post in profile.get_posts():

                # Reels are videos, so we filter video posts
                if post.is_video:

                    # Send the reel video to Telegram
                    bot.send_video(call.message.chat.id, post.video_url)

                    # Increase reel counter
                    count += 1

                # Stop after sending 10 reels
                if count >= 10:
                    break

            # Inform user when reels sending is complete
            if count == 0:
                bot.send_message(call.message.chat.id, "No reels found for this profile.")
            else:
                bot.send_message(call.message.chat.id, "Finished sending reels.")

        except Exception as e:

            # Handle possible errors like private profile or request block
            bot.send_message(
                call.message.chat.id,
                "Error fetching reels. The profile might be private or Instagram blocked the request."
            )

    elif action == "stories":

        # Inform the user that story fetching has started
        bot.send_message(call.message.chat.id, f"Fetching active stories from {username}...")

        try:
            # Load Instagram profile
            profile = instaloader.Profile.from_username(loader.context, username)

            # Get user ID from profile
            user_id = profile.userid

            # Fetch stories of that user
            stories = loader.get_stories(userids=[user_id])

            story_found = False

            # Loop through stories
            for story in stories:
                for item in story.get_items():

                    story_found = True

                    # If story is video send video
                    if item.is_video:
                        bot.send_video(call.message.chat.id, item.video_url)

                    # If story is photo send photo
                    else:
                        bot.send_photo(call.message.chat.id, item.url)

            # If no stories exist
            if not story_found:
                bot.send_message(call.message.chat.id, "No active stories found.")

            else:
                bot.send_message(call.message.chat.id, "Finished sending stories.")

        except Exception as e:

            # Handle errors (private profile, login required, etc.)
            bot.send_message(
                call.message.chat.id,
                "Unable to fetch stories. Stories may require Instagram login or the profile is private."
            )

    elif action == "dp":

        try:
            bot.send_message(call.message.chat.id, "Downloading profile picture...")

            profile = instaloader.Profile.from_username(loader.context, username)

            pic_url = profile.profile_pic_url

            bot.send_photo(call.message.chat.id, pic_url)

        except Exception as e:
            bot.send_message(call.message.chat.id, "Profile not found or Instagram blocked the request.")

bot.infinity_polling()
