import os
import logging

import telebot
from flask import Flask, request

# =========================
# CONFIG
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing")

if not WEBHOOK_URL:
    raise RuntimeError("WEBHOOK_URL environment variable is missing")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)


# =========================
# TEST COMMANDS
# =========================

@bot.message_handler(commands=["start"])
def start_command(message):
    logging.info(
        "START HANDLER FIRED | user=%s | chat=%s",
        message.from_user.id,
        message.chat.id
    )

    bot.send_message(
        message.chat.id,
        "👋 Welcome to SpeedFistt Store!\n\n"
        "✅ BOT IS WORKING!\n\n"
        "💰 /balance\n"
        "🛍 /products"
    )


@bot.message_handler(commands=["ping"])
def ping_command(message):
    logging.info(
        "PING HANDLER FIRED | user=%s | chat=%s",
        message.from_user.id,
        message.chat.id
    )

    bot.send_message(
        message.chat.id,
        "🏓 PONG!\n\n"
        "Telegram → Webhook → Bot ✅"
    )


@bot.message_handler(commands=["balance"])
def balance_command(message):
    bot.send_message(
        message.chat.id,
        "💰 Balance system connected."
    )


@bot.message_handler(commands=["products"])
def products_command(message):
    bot.send_message(
        message.chat.id,
        "🛍 SPEEDFISTT STORE\n\n"
        "Digital Product A — ₹100\n"
        "Digital Product B — ₹200"
    )


# =========================
# WEBHOOK
# =========================

@app.route("/", methods=["GET"])
def home():
    return "SpeedFistt Store Bot is running.", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_data().decode("utf-8")

        logging.info("TELEGRAM UPDATE RECEIVED: %s", data)

        update = telebot.types.Update.de_json(data)

        bot.process_new_updates([update])

        logging.info("UPDATE PROCESSED SUCCESSFULLY")

        return "OK", 200

    except Exception:
        logging.exception("WEBHOOK ERROR")
        return "ERROR", 500


# =========================
# SET WEBHOOK
# =========================

def setup_webhook():
    webhook_url = f"{WEBHOOK_URL}/webhook"

    bot.remove_webhook()
    bot.set_webhook(
        url=webhook_url,
        allowed_updates=["message"]
    )

    logging.info(
        "WEBHOOK SET: %s",
        webhook_url
    )


setup_webhook()


# =========================
# RUN
# =========================

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port
    )
