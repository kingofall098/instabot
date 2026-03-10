
import telebot

TOKEN = "8755937047:AAHBFaKCan-W8QLls2DDJ3-XpUdyw3tP16w"

bot = telebot.TeleBot(TOKEN)

# PHOTO
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    file_id = message.photo[-1].file_id
    bot.send_photo(message.chat.id, file_id)

# VIDEO
@bot.message_handler(content_types=['video'])
def handle_video(message):
    file_id = message.video.file_id
    bot.send_video(message.chat.id, file_id)

# DOCUMENT
@bot.message_handler(content_types=['document'])
def handle_doc(message):
    file_id = message.document.file_id
    bot.send_document(message.chat.id, file_id)

# AUDIO
@bot.message_handler(content_types=['audio'])
def handle_audio(message):
    file_id = message.audio.file_id
    bot.send_audio(message.chat.id, file_id)

# STICKER
@bot.message_handler(content_types=['sticker'])
def handle_sticker(message):
    file_id = message.sticker.file_id
    bot.send_sticker(message.chat.id, file_id)

# TEXT (optional)
@bot.message_handler(content_types=['text'])
def handle_text(message):
    bot.send_message(message.chat.id, message.text)

bot.infinity_polling()
