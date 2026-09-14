```python
import os
import threading
import logging

import telebot
from flask import Flask, request

# ==========================================
# CONFIG
# ==========================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")

ADMIN_ID = 1003892586354
CHANNEL_ID = -1003892586354
BALANCE_MESSAGE_ID = 4

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing")

if not WEBHOOK_URL:
    raise RuntimeError("WEBHOOK_URL environment variable is missing")

# ==========================================
# BOT
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

bot = telebot.TeleBot(
    BOT_TOKEN,
    threaded=False
)

app = Flask(__name__)

balance_lock = threading.Lock()

# ==========================================
# BALANCE DATABASE
# ==========================================

def parse_balances(text):
    balances = {}

    for line in text.splitlines():
        line = line.strip()

        if not line.startswith("USER:"):
            continue

        try:
            user_part, balance_part = line.split("|")

            user_id = int(
                user_part.split(":", 1)[1].strip()
            )

            balance = int(
                float(balance_part.split(":", 1)[1].strip())
            )

            balances[user_id] = balance

        except (ValueError, IndexError):
            continue

    return balances


def format_balances(balances):
    lines = [
        "💰 SPEEDFISTT BALANCE DATABASE",
        ""
    ]

    if not balances:
        lines.append("No users registered yet.")
    else:
        for user_id in sorted(balances):
            lines.append(
                f"USER: {user_id} | BALANCE: {balances[user_id]}"
            )

    return "\n".join(lines)


def read_balance_message():
    """
    Telegram Bot API does not provide a normal method
    to fetch an arbitrary old channel message.

    We temporarily forward the fixed database message
    to the admin chat, read it, then delete the temporary copy.
    """

    forwarded = bot.forward_message(
        chat_id=ADMIN_ID,
        from_chat_id=CHANNEL_ID,
        message_id=BALANCE_MESSAGE_ID
    )

    try:
        return forwarded.text or ""
    finally:
        try:
            bot.delete_message(
                ADMIN_ID,
                forwarded.message_id
            )
        except Exception:
            pass


def get_balances():
    text = read_balance_message()
    return parse_balances(text)


def save_balances(balances):
    new_text = format_balances(balances)

    bot.edit_message_text(
        text=new_text,
        chat_id=CHANNEL_ID,
        message_id=BALANCE_MESSAGE_ID
    )


# ==========================================
# START
# ==========================================

@bot.message_handler(commands=["start"])
def start_command(message):
    user_id = message.from_user.id

    try:
        with balance_lock:
            balances = get_balances()

            if user_id not in balances:
                balances[user_id] = 0
                save_balances(balances)

        bot.send_message(
            message.chat.id,
            "👋 Welcome to SpeedFistt Store!\n\n"
            "💰 /balance - Check balance\n"
            "🛍 /products - View products\n\n"
            "To buy:\n"
            "/buy 1\n"
            "/buy 2"
        )

    except Exception:
        logging.exception("START ERROR")

        bot.send_message(
            message.chat.id,
            "❌ Store setup error.\n"
            "Please contact admin."
        )


# ==========================================
# BALANCE
# ==========================================

@bot.message_handler(commands=["balance"])
def balance_command(message):
    user_id = message.from_user.id

    try:
        balances = get_balances()
        balance = balances.get(user_id, 0)

        bot.send_message(
            message.chat.id,
            f"💰 Your balance: ₹{balance}"
        )

    except Exception:
        logging.exception("BALANCE ERROR")

        bot.send_message(
            message.chat.id,
            "❌ Could not check balance."
        )


# ==========================================
# PRODUCTS
# ==========================================

PRODUCTS = {
    1: {
        "name": "Digital Product A",
        "price": 100
    },
    2: {
        "name": "Digital Product B",
        "price": 200
    }
}


@bot.message_handler(commands=["products"])
def products_command(message):
    bot.send_message(
        message.chat.id,
        "🛍 SPEEDFISTT STORE\n\n"
        "1️⃣ Digital Product A — ₹100\n"
        "   Buy: /buy 1\n\n"
        "2️⃣ Digital Product B — ₹200\n"
        "   Buy: /buy 2"
    )


# ==========================================
# ADMIN ADD BALANCE
# ==========================================

@bot.message_handler(commands=["add"])
def add_balance(message):

    if message.from_user.id != ADMIN_ID:
        bot.send_message(
            message.chat.id,
            "❌ Admin only."
        )
        return

    parts = message.text.split()

    if len(parts) != 3:
        bot.send_message(
            message.chat.id,
            "❌ Correct format:\n\n"
            "/add USER_ID AMOUNT\n\n"
            "Example:\n"
            "/add 123456789 500"
        )
        return

    try:
        user_id = int(parts[1])
        amount = int(parts[2])

    except ValueError:
        bot.send_message(
            message.chat.id,
            "❌ User ID and amount must be numbers."
        )
        return

    if user_id <= 0:
        bot.send_message(
            message.chat.id,
            "❌ Invalid User ID."
        )
        return

    if amount <= 0:
        bot.send_message(
            message.chat.id,
            "❌ Amount must be greater than ₹0."
        )
        return

    if amount > 1000000:
        bot.send_message(
            message.chat.id,
            "❌ Maximum allowed amount is ₹10,00,000."
        )
        return

    try:
        with balance_lock:

            balances = get_balances()

            old_balance = balances.get(
                user_id,
                0
            )

            new_balance = old_balance + amount

            balances[user_id] = new_balance

            save_balances(balances)

        bot.send_message(
            message.chat.id,
            "✅ BALANCE ADDED\n\n"
            f"👤 User ID: {user_id}\n"
            f"💵 Added: ₹{amount}\n"
            f"💰 New Balance: ₹{new_balance}"
        )

        # Notify user if they have already started the bot
        try:
            bot.send_message(
                user_id,
                "💰 Balance Added!\n\n"
                f"Added: ₹{amount}\n"
                f"Current Balance: ₹{new_balance}"
            )

        except Exception:
            logging.info(
                "Could not notify user %s",
                user_id
            )

    except Exception:
        logging.exception("ADD BALANCE ERROR")

        bot.send_message(
            message.chat.id,
            "❌ Balance update failed."
        )


# ==========================================
# BUY
# ==========================================

@bot.message_handler(commands=["buy"])
def buy_product(message):

    parts = message.text.split()

    if len(parts) != 2:
        bot.send_message(
            message.chat.id,
            "❌ Correct format:\n\n"
            "/buy 1\n"
            "or\n"
            "/buy 2"
        )
        return

    try:
        product_id = int(parts[1])

    except ValueError:
        bot.send_message(
            message.chat.id,
            "❌ Invalid product."
        )
        return

    if product_id not in PRODUCTS:
        bot.send_message(
            message.chat.id,
            "❌ Product not found."
        )
        return

    product = PRODUCTS[product_id]

    user_id = message.from_user.id
    price = product["price"]
    product_name = product["name"]

    try:
        with balance_lock:

            balances = get_balances()

            current_balance = balances.get(
                user_id,
                0
            )

            if current_balance < price:
                bot.send_message(
                    message.chat.id,
                    "❌ Insufficient balance.\n\n"
                    f"Product: {product_name}\n"
                    f"Price: ₹{price}\n"
                    f"Your balance: ₹{current_balance}"
                )
                return

            new_balance = current_balance - price

            balances[user_id] = new_balance

            save_balances(balances)

        bot.send_message(
            message.chat.id,
            "✅ PURCHASE SUCCESSFUL!\n\n"
            f"🛍 Product: {product_name}\n"
            f"💵 Price: ₹{price}\n"
            f"💰 Remaining Balance: ₹{new_balance}"
        )

    except Exception:
        logging.exception("PURCHASE ERROR")

        bot.send_message(
            message.chat.id,
            "❌ Purchase failed."
        )


# ==========================================
# WEBHOOK
# ==========================================

@app.route("/", methods=["GET"])
def home():
    return "SpeedFistt Store Bot is running.", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_data().decode("utf-8")

        logging.info(
            "TELEGRAM UPDATE RECEIVED: %s",
            data
        )

        update = telebot.types.Update.de_json(data)

        bot.process_new_updates([update])

        logging.info(
            "UPDATE PROCESSED SUCCESSFULLY"
        )

        return "OK", 200

    except Exception:
        logging.exception("WEBHOOK ERROR")
        return "ERROR", 500


# ==========================================
# SET WEBHOOK
# ==========================================

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


# ==========================================
# RUN
# ==========================================

if __name__ == "__main__":

    port = int(
        os.getenv("PORT", "10000")
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
```
