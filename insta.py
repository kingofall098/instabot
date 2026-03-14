import telebot
import requests

TOKEN = "8756448611:AAHbnOlBbZP8639ZKHcFZd0vSQeK54EMSYQ"

headers = {
    "User-Agent": "Mozilla/5.0"
}

bot = telebot.TeleBot(TOKEN)


def get_media(url):

    try:

        if "instagram.com" not in url:
            return None

        if "?" in url:
            url = url.split("?")[0]

        if not url.endswith("/"):
            url += "/"

        api = url + "?__a=1&__d=dis"

        r = requests.get(api, headers=headers)

        if r.status_code != 200:
            return None

        data = r.json()

        media = data["graphql"]["shortcode_media"]

        items = []

        if media["__typename"] == "GraphImage":
            items.append({
                "type": "photo",
                "url": media["display_url"]
            })

        elif media["__typename"] == "GraphVideo":
            items.append({
                "type": "video",
                "url": media["video_url"]
            })

        elif media["__typename"] == "GraphSidecar":

            for edge in media["edge_sidecar_to_children"]["edges"]:

                node = edge["node"]

                if node["is_video"]:
                    items.append({
                        "type": "video",
                        "url": node["video_url"]
                    })
                else:
                    items.append({
                        "type": "photo",
                        "url": node["display_url"]
                    })

        return items

    except:
        return None


@bot.message_handler(commands=['start'])
def start(message):

    bot.reply_to(
        message,
        "Send an Instagram link and I will download the media."
    )


@bot.message_handler(func=lambda m: m.text and "instagram.com" in m.text)
def download(message):

    bot.reply_to(message, "Downloading media...")

    media = get_media(message.text)

    if not media:
        bot.reply_to(message, "Could not download media.")
        return

    for item in media:

        if item["type"] == "photo":

            bot.send_photo(
                message.chat.id,
                item["url"]
            )

        else:

            bot.send_video(
                message.chat.id,
                item["url"]
            )


print("Bot running...")
bot.infinity_polling()
