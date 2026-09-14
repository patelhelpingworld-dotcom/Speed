import os
import threading
import logging

import telebot
from flask import Flask, request

# =========================
# CONFIG
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")

ADMIN_ID = 1003892586354
CHANNEL_ID = -1003892586354
BALANCE_MESSAGE_ID = 4

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing")

if not WEBHOOK_URL:
    raise RuntimeError("WEBHOOK_URL environment variable is missing")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# One process = one lock
balance_lock = threading.Lock()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# =========================
# BALANCE STORAGE
# =========================

def parse_balances(text):
    balances = {}

    for line in text.splitlines():
        line = line.strip()

        if not line:
            continue

        if line.startswith("USER:"):
            try:
                parts = line.split("|")

                user_id = int(parts[0].split(":")[1].strip())
                balance = float(parts[1].split(":")[1].strip())

                balances[user_id] = balance
            except (ValueError, IndexError):
                continue

    return balances


def format_balances(balances):
    lines = ["💰 SPEEDFISTT BALANCE DATABASE", ""]

    if not balances:
        lines.append("No users registered yet.")
    else:
        for user_id in sorted(balances):
            amount = balances[user_id]

            if amount.is_integer():
                amount_text = str(int(amount))
            else:
                amount_text = f"{amount:.2f}"

            lines.append(
                f"USER: {user_id} | BALANCE: {amount_text}"
            )

    return "\n".join(lines)


def read_balance_message():
    """
    Telegram Bot API does not provide a normal 'get old channel message'
    endpoint.

    We temporarily forward the fixed balance message to the admin chat,
    read its text, then delete the temporary forwarded message.
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


def update_balance_message(balances):
    new_text = format_balances(balances)

    bot.edit_message_text(
        new_text,
        chat_id=CHANNEL_ID,
        message_id=BALANCE_MESSAGE_ID
    )


def get_balances():
    text = read_balance_message()
    return parse_balances(text)


# =========================
# USER COMMANDS
# =========================

@bot.message_handler(commands=["start"])
def start_command(message):
    user_id = message.from_user.id

    try:
        with balance_lock:
            balances = get_balances()

            if user_id not in balances:
                balances[user_id] = 0.0
                update_balance_message(balances)

        bot.reply_to(
            message,
            "👋 Welcome to SpeedFistt Store!\n\n"
            "💰 /balance - Check your balance\n"
            "🛍 /products - View products"
        )

    except Exception as e:
        logging.exception("Start error")
        bot.reply_to(
            message,
            "❌ Setup error. Please contact admin."
        )


@bot.message_handler(commands=["balance"])
def balance_command(message):
    user_id = message.from_user.id

    try:
        balances = get_balances()
        balance = balances.get(user_id, 0.0)

        bot.reply_to(
            message,
            f"💰 Your balance: ₹{balance:.2f}"
        )

    except Exception:
        logging.exception("Balance error")
        bot.reply_to(
            message,
            "❌ Could not check balance."
        )


@bot.message_handler(commands=["products"])
def products_command(message):
    bot.reply_to(
        message,
        "🛍 SPEEDFISTT STORE\n\n"
        "1️⃣ Digital Product A — ₹100\n"
        "2️⃣ Digital Product B — ₹200\n\n"
        "Use:\n"
        "/buy 1\n"
        "/buy 2"
    )


# =========================
# ADMIN ADD BALANCE
# =========================

@bot.message_handler(commands=["add"])
def add_balance(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Admin only.")
        return

    parts = message.text.split()

    if len(parts) != 3:
        bot.reply_to(
            message,
            "Usage:\n/add USER_ID AMOUNT\n\n"
            "Example:\n/add 123456789 500"
        )
        return

    try:
        user_id = int(parts[1])
        amount = float(parts[2])

        if amount <= 0:
            bot.reply_to(message, "❌ Amount must be greater than 0.")
            return

        if amount > 1000000:
            bot.reply_to(message, "❌ Amount is too large.")
            return

    except ValueError:
        bot.reply_to(message, "❌ Invalid User ID or amount.")
        return

    try:
        with balance_lock:
            balances = get_balances()

            old_balance = balances.get(user_id, 0.0)
            new_balance = old_balance + amount

            balances[user_id] = new_balance

            update_balance_message(balances)

        bot.reply_to(
            message,
            f"✅ Balance added\n\n"
            f"👤 User: {user_id}\n"
            f"💵 Added: ₹{amount:.2f}\n"
            f"💰 New balance: ₹{new_balance:.2f}"
        )

        try:
            bot.send_message(
                user_id,
                f"💰 Balance Added!\n\n"
                f"Added: ₹{amount:.2f}\n"
                f"Current Balance: ₹{new_balance:.2f}"
            )
        except Exception:
            logging.info("Could not notify user %s", user_id)

    except Exception:
        logging.exception("Add balance error")
        bot.reply_to(
            message,
            "❌ Balance update failed."
        )


# =========================
# PURCHASE
# =========================

PRODUCTS = {
    1: ("Digital Product A", 100.0),
    2: ("Digital Product B", 200.0),
}


@bot.message_handler(commands=["buy"])
def buy_product(message):
    parts = message.text.split()

    if len(parts) != 2:
        bot.reply_to(
            message,
            "Usage:\n/buy 1\nor\n/buy 2"
        )
        return

    try:
        product_id = int(parts[1])
    except ValueError:
        bot.reply_to(message, "❌ Invalid product.")
        return

    if product_id not in PRODUCTS:
        bot.reply_to(message, "❌ Product not found.")
        return

    product_name, price = PRODUCTS[product_id]
    user_id = message.from_user.id

    try:
        with balance_lock:
            balances = get_balances()

            current_balance = balances.get(user_id, 0.0)

            if current_balance < price:
                bot.reply_to(
                    message,
                    f"❌ Insufficient balance.\n\n"
                    f"Price: ₹{price:.2f}\n"
                    f"Your balance: ₹{current_balance:.2f}"
                )
                return

            new_balance = current_balance - price
            balances[user_id] = new_balance

            update_balance_message(balances)

        bot.reply_to(
            message,
            f"✅ Purchase successful!\n\n"
            f"🛍 Product: {product_name}\n"
            f"💵 Price: ₹{price:.2f}\n"
            f"💰 Remaining balance: ₹{new_balance:.2f}"
        )

    except Exception:
        logging.exception("Purchase error")
        bot.reply_to(
            message,
            "❌ Purchase failed."
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
        json_string = request.get_data().decode("utf-8")

        logging.info(
            "TELEGRAM UPDATE RECEIVED: %s",
            json_string
        )

        update = telebot.types.Update.de_json(json_string)

        bot.process_new_updates([update])

        logging.info("UPDATE PROCESSED SUCCESSFULLY")

        return "OK", 200

    except Exception:
        logging.exception("WEBHOOK ERROR")
        return "ERROR", 500


# =========================
# START WEBHOOK
# =========================

def setup_webhook():
    webhook_address = f"{WEBHOOK_URL}/webhook"

    bot.remove_webhook()

    bot.set_webhook(
        url=webhook_address,
        allowed_updates=["message"]
    )

    logging.info(
        "Webhook set successfully: %s",
        webhook_address
    )



setup_webhook()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port
    )
