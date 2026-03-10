
import telebot
import json
import os

TOKEN = "8755937047:AAHBFaKCan-W8QLls2DDJ3-XpUdyw3tP16w"
ADMIN_ID = 8648483733  # put your telegram id here

bot = telebot.TeleBot(TOKEN)

DATA_FILE = "data.json"
REQUIRED_GROUP = None
from telebot.types import ReplyKeyboardMarkup, KeyboardButton


# ---------- LOAD DATA ----------
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"users": [], "media_count": 0}
    with open(DATA_FILE, "r") as f:
        return json.load(f)


# ---------- SAVE DATA ----------
def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)


data = load_data()
def is_user_joined(user_id):

    if REQUIRED_GROUP is None:
        return True

    try:
        member = bot.get_chat_member(REQUIRED_GROUP, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

def firewall(message):

    user_id = message.from_user.id

    if not is_user_joined(user_id):

        markup = InlineKeyboardMarkup()

        join_btn = InlineKeyboardButton(
            "🔗 Join Group",
            url=f"https://t.me/{REQUIRED_GROUP.replace('@','')}"
        )

        markup.add(join_btn)

        bot.send_message(
            message.chat.id,
            "🚫 Access Denied\n\n"
            "You must join the group before using this bot.",
            reply_markup=markup
        )

        return False

    return True
# ---------- START ----------
# @bot.message_handler(commands=['start'])
# def start(message):

#     user_id = message.from_user.id

#     if user_id not in data["users"]:
#         data["users"].append(user_id)
#         save_data(data)

#     text = (
#         "👋 Welcome!\n\n"
#         "This is an Anonymous Media Relay Bot.\n\n"
#         "Send any media and the bot will resend it anonymously."
#     )

#     bot.send_message(message.chat.id, text)
@bot.message_handler(commands=['start'])
def start(message):

    if not firewall(message):
        return

    user_id = message.from_user.id

    if user_id not in data["users"]:
        data["users"].append(user_id)
        save_data(data)

    bot.send_message(
        message.chat.id,
        "👋 Welcome!\n\n"
        "This is an Anonymous Media Relay Bot.\n\n"
        "Send any media and the bot will resend it anonymously."
    )
broadcast_mode = False
def admin_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)

    stats = KeyboardButton("📊 Statistics")
    broadcast = KeyboardButton("📢 Broadcast")

    kb.add(stats)
    kb.add(broadcast)

    return kb

@bot.message_handler(func=lambda m: m.text == "📊 Statistics")
def show_stats(message):

    if message.from_user.id != ADMIN_ID:
        return

    users = len(data["users"])
    media = data["media_count"]

    text = (
        "📊 Bot Statistics\n\n"
        f"👥 Total Users: {users}\n"
        f"📤 Total Media Sent: {media}"
    )

    bot.send_message(message.chat.id, text)
@bot.message_handler(func=lambda m: m.text == "📢 Broadcast")
def broadcast_start(message):

    global broadcast_mode

    if message.from_user.id != ADMIN_ID:
        return

    broadcast_mode = True

    bot.send_message(message.chat.id, "Send the message you want to broadcast.")
@bot.message_handler(func=lambda m: broadcast_mode and m.from_user.id == ADMIN_ID)
def send_broadcast(message):

    global broadcast_mode

    for user in data["users"]:
        try:
            bot.send_message(user, message.text)
        except:
            pass

    broadcast_mode = False

    bot.send_message(message.chat.id, "✅ Broadcast sent to all users.")
# ---------- MEDIA HANDLER ----------
@bot.message_handler(content_types=[
    'photo','video','document','audio',
    'voice','sticker','animation','video_note'
])
def relay_media(message):

    chat_id = message.chat.id

    try:

        if message.photo:
            bot.send_photo(chat_id, message.photo[-1].file_id)

        elif message.video:
            bot.send_video(chat_id, message.video.file_id)

        elif message.document:
            bot.send_document(chat_id, message.document.file_id)

        elif message.audio:
            bot.send_audio(chat_id, message.audio.file_id)

        elif message.voice:
            bot.send_voice(chat_id, message.voice.file_id)

        elif message.animation:
            bot.send_animation(chat_id, message.animation.file_id)

        elif message.sticker:
            bot.send_sticker(chat_id, message.sticker.file_id)

        elif message.video_note:
            bot.send_video_note(chat_id, message.video_note.file_id)

        # update stats
        data["media_count"] += 1
        save_data(data)

        bot.delete_message(chat_id, message.message_id)

    except Exception as e:
        print(e)


# ---------- ADMIN PANEL ----------
@bot.message_handler(commands=['admin'])
def admin_panel(message):

    if message.from_user.id != ADMIN_ID:
        return

    bot.send_message(
        message.chat.id,
        "🔐 Admin Panel",
        reply_markup=admin_keyboard()
    )


bot.infinity_polling()
