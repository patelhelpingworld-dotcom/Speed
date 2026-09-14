import os
import threading
import logging
import uuid
from datetime import datetime

import telebot
from telebot import types
from flask import Flask, request


# ==========================================
# CONFIG
# ==========================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")

# These are your currently working IDs.
ADMIN_ID = 1006157952
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

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

balance_lock = threading.Lock()


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

MAX_SAVED_ORDERS = 50


# ==========================================
# REPLY-KEYBOARD MENUS
# No inline buttons are used.
# ==========================================

def main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=2
    )

    markup.add(
        types.KeyboardButton("ðŸ› Products"),
        types.KeyboardButton("ðŸ’° Balance")
    )
    markup.add(
        types.KeyboardButton("ðŸ“œ My Orders"),
        types.KeyboardButton("ðŸ‘¤ Profile")
    )

    if user_id == ADMIN_ID:
        markup.add(types.KeyboardButton("ðŸ‘¨â€ðŸ’¼ Admin Panel"))

    return markup


def admin_menu():
    markup = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=2
    )
    markup.add(
        types.KeyboardButton("ðŸ’³ Add Balance"),
        types.KeyboardButton("ðŸ“Š Statistics")
    )
    markup.add(types.KeyboardButton("ðŸ  Main Menu"))
    return markup


# ==========================================
# CHANNEL DATABASE
#
# One fixed channel message stores:
# - balances
# - order history
#
# This keeps the existing channel-database design.
# ==========================================

def parse_database(text):
    balances = {}
    orders = []

    for line in text.splitlines():
        line = line.strip()

        # Balance line:
        # USER: 123 | BALANCE: 500
        if line.startswith("USER:") and "|" in line:
            try:
                user_part, balance_part = line.split("|", 1)
                user_id = int(user_part.split(":", 1)[1].strip())
                balance = int(
                    float(balance_part.split(":", 1)[1].strip())
                )
                balances[user_id] = balance
            except (ValueError, IndexError):
                continue

        # Order line:
        # ORDER: ID | USER: 123 | PRODUCT: Product | PRICE: 100 | TIME: ...
        elif line.startswith("ORDER:") and "|" in line:
            try:
                parts = [x.strip() for x in line.split("|")]
                order = {}

                for part in parts:
                    key, value = part.split(":", 1)
                    order[key.strip().lower()] = value.strip()

                order["user"] = int(order["user"])
                order["price"] = int(float(order["price"]))
                orders.append(order)
            except (ValueError, IndexError):
                continue

    return balances, orders


def format_database(balances, orders):
    lines = [
        "ðŸ’° SPEEDFISTT STORE DATABASE",
        "",
        "ðŸ“Š STATISTICS",
        f"USERS: {len(balances)}",
        f"ORDERS: {len(orders)}",
        f"REVENUE: â‚¹{sum(o.get('price', 0) for o in orders)}",
        "",
        "ðŸ’³ BALANCES"
    ]

    if not balances:
        lines.append("No users registered yet.")
    else:
        for user_id in sorted(balances):
            lines.append(
                f"USER: {user_id} | BALANCE: {balances[user_id]}"
            )

    lines.extend(["", "ðŸ“œ RECENT ORDERS"])

    if not orders:
        lines.append("No orders yet.")
    else:
        # Keep newest orders at the bottom.
        for order in orders[-MAX_SAVED_ORDERS:]:
            lines.append(
                f"ORDER: {order.get('id', 'N/A')} | "
                f"USER: {order.get('user', 0)} | "
                f"PRODUCT: {order.get('product', 'Unknown')} | "
                f"PRICE: {order.get('price', 0)} | "
                f"TIME: {order.get('time', 'N/A')}"
            )

    text = "\n".join(lines)

    # Telegram text messages have a size limit.
    # If the database grows too much, retain only the newest orders.
    if len(text) > 3900 and len(orders) > 1:
        return format_database(
            balances,
            orders[-max(1, len(orders) // 2):]
        )

    return text


def read_database_message():
    """
    Telegram Bot API does not provide a normal method to fetch
    an arbitrary old channel message.

    We temporarily forward the fixed database message to the
    admin chat, read it, then delete the temporary copy.
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


def get_database():
    text = read_database_message()
    return parse_database(text)


def save_database(balances, orders):
    new_text = format_database(balances, orders)

    bot.edit_message_text(
        text=new_text,
        chat_id=CHANNEL_ID,
        message_id=BALANCE_MESSAGE_ID
    )


# ==========================================
# CHANNEL DEBUG
# If a new channel post arrives, logs reveal
# the real channel ID and message ID.
# ==========================================

@bot.channel_post_handler(func=lambda message: True)
def channel_post_debug(message):
    logging.info(
        "CHANNEL FOUND | chat_id=%s | message_id=%s | text=%s",
        message.chat.id,
        message.message_id,
        message.text
    )


# ==========================================
# START / MAIN MENU
# ==========================================

@bot.message_handler(commands=["start"])
def start_command(message):
    user_id = message.from_user.id

    try:
        with balance_lock:
            balances, orders = get_database()

            if user_id not in balances:
                balances[user_id] = 0
                save_database(balances, orders)

        bot.send_message(
            message.chat.id,
            "ðŸ‘‹ Welcome to SpeedFistt Store!\n\n"
            "Choose an option from the menu below.",
            reply_markup=main_menu(user_id)
        )

    except Exception:
        logging.exception("START ERROR")
        bot.send_message(
            message.chat.id,
            "âŒ Store setup error.\nPlease contact admin."
        )


# ==========================================
# BALANCE
# ==========================================

def send_balance(chat_id, user_id):
    try:
        balances, _ = get_database()
        balance = balances.get(user_id, 0)

        bot.send_message(
            chat_id,
            "ðŸ’° YOUR BALANCE\n\n"
            f"Available: â‚¹{balance}",
            reply_markup=main_menu(user_id)
        )
    except Exception:
        logging.exception("BALANCE ERROR")
        bot.send_message(
            chat_id,
            "âŒ Could not check balance.",
            reply_markup=main_menu(user_id)
        )


@bot.message_handler(commands=["balance"])
def balance_command(message):
    send_balance(message.chat.id, message.from_user.id)


@bot.message_handler(func=lambda m: m.text == "ðŸ’° Balance")
def balance_button(message):
    send_balance(message.chat.id, message.from_user.id)


# ==========================================
# PRODUCTS
# ==========================================

def send_products(chat_id, user_id):
    text = "ðŸ› SPEEDFISTT STORE\n\n"

    for product_id, product in PRODUCTS.items():
        text += (
            f"{product_id}ï¸âƒ£ {product['name']}\n"
            f"ðŸ’µ Price: â‚¹{product['price']}\n"
            f"ðŸ›’ Buy: /buy {product_id}\n\n"
        )

    text += "Type the shown /buy command to purchase."

    bot.send_message(
        chat_id,
        text,
        reply_markup=main_menu(user_id)
    )


@bot.message_handler(commands=["products"])
def products_command(message):
    send_products(message.chat.id, message.from_user.id)


@bot.message_handler(func=lambda m: m.text == "ðŸ› Products")
def products_button(message):
    send_products(message.chat.id, message.from_user.id)


# ==========================================
# BUY
# ==========================================

@bot.message_handler(commands=["buy"])
def buy_product(message):
    parts = message.text.split()

    if len(parts) != 2:
        bot.send_message(
            message.chat.id,
            "âŒ Correct format:\n\n/buy 1\nor\n/buy 2",
            reply_markup=main_menu(message.from_user.id)
        )
        return

    try:
        product_id = int(parts[1])
    except ValueError:
        bot.send_message(
            message.chat.id,
            "âŒ Invalid product.",
            reply_markup=main_menu(message.from_user.id)
        )
        return

    if product_id not in PRODUCTS:
        bot.send_message(
            message.chat.id,
            "âŒ Product not found.",
            reply_markup=main_menu(message.from_user.id)
        )
        return

    product = PRODUCTS[product_id]
    user_id = message.from_user.id
    price = product["price"]
    product_name = product["name"]

    try:
        with balance_lock:
            balances, orders = get_database()

            current_balance = balances.get(user_id, 0)

            if current_balance < price:
                bot.send_message(
                    message.chat.id,
                    "âŒ INSUFFICIENT BALANCE\n\n"
                    f"Product: {product_name}\n"
                    f"Price: â‚¹{price}\n"
                    f"Your balance: â‚¹{current_balance}",
                    reply_markup=main_menu(user_id)
                )
                return

            new_balance = current_balance - price
            balances[user_id] = new_balance

            order = {
                "id": uuid.uuid4().hex[:8].upper(),
                "user": user_id,
                "product": product_name,
                "price": price,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M")
            }

            orders.append(order)
            save_database(balances, orders)

        bot.send_message(
            message.chat.id,
            "âœ… PURCHASE SUCCESSFUL!\n\n"
            f"ðŸ§¾ Order ID: #{order['id']}\n"
            f"ðŸ› Product: {product_name}\n"
            f"ðŸ’µ Price: â‚¹{price}\n"
            f"ðŸ’° Remaining Balance: â‚¹{new_balance}",
            reply_markup=main_menu(user_id)
        )

    except Exception:
        logging.exception("PURCHASE ERROR")
        bot.send_message(
            message.chat.id,
            "âŒ Purchase failed.",
            reply_markup=main_menu(user_id)
        )


# ==========================================
# ORDER HISTORY
# ==========================================

def send_orders(chat_id, user_id):
    try:
        _, orders = get_database()
        user_orders = [o for o in orders if o.get("user") == user_id]

        if not user_orders:
            text = "ðŸ“œ MY ORDERS\n\nNo purchases yet."
        else:
            text = "ðŸ“œ MY ORDERS\n\n"
            for order in reversed(user_orders[-20:]):
                text += (
                    f"ðŸ§¾ #{order.get('id', 'N/A')}\n"
                    f"ðŸ› {order.get('product', 'Unknown')}\n"
                    f"ðŸ’µ â‚¹{order.get('price', 0)}\n"
                    f"ðŸ• {order.get('time', 'N/A')}\n\n"
                )

        bot.send_message(
            chat_id,
            text,
            reply_markup=main_menu(user_id)
        )

    except Exception:
        logging.exception("ORDERS ERROR")
        bot.send_message(
            chat_id,
            "âŒ Could not load order history.",
            reply_markup=main_menu(user_id)
        )


@bot.message_handler(commands=["orders"])
def orders_command(message):
    send_orders(message.chat.id, message.from_user.id)


@bot.message_handler(func=lambda m: m.text == "ðŸ“œ My Orders")
def orders_button(message):
    send_orders(message.chat.id, message.from_user.id)


# ==========================================
# PROFILE
# ==========================================

@bot.message_handler(commands=["profile"])
def profile_command(message):
    user = message.from_user

    try:
        balances, orders = get_database()
        balance = balances.get(user.id, 0)
        total_orders = sum(
            1 for o in orders if o.get("user") == user.id
        )

        username = f"@{user.username}" if user.username else "Not set"

        bot.send_message(
            message.chat.id,
            "ðŸ‘¤ MY PROFILE\n\n"
            f"ðŸ†” User ID: {user.id}\n"
            f"ðŸ‘¤ Username: {username}\n"
            f"ðŸ’° Balance: â‚¹{balance}\n"
            f"ðŸ“œ Orders: {total_orders}",
            reply_markup=main_menu(user.id)
        )

    except Exception:
        logging.exception("PROFILE ERROR")
        bot.send_message(
            message.chat.id,
            "âŒ Could not load profile.",
            reply_markup=main_menu(user.id)
        )


@bot.message_handler(func=lambda m: m.text == "ðŸ‘¤ Profile")
def profile_button(message):
    profile_command(message)


# ==========================================
# ADMIN PANEL
# ==========================================

@bot.message_handler(func=lambda m: m.text == "ðŸ‘¨â€ðŸ’¼ Admin Panel")
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        bot.send_message(
            message.chat.id,
            "âŒ Admin only.",
            reply_markup=main_menu(message.from_user.id)
        )
        return

    bot.send_message(
        message.chat.id,
        "ðŸ‘¨â€ðŸ’¼ ADMIN PANEL\n\n"
        "Use the buttons below.",
        reply_markup=admin_menu()
    )


@bot.message_handler(func=lambda m: m.text == "ðŸ  Main Menu")
def home_button(message):
    bot.send_message(
        message.chat.id,
        "ðŸ  MAIN MENU",
        reply_markup=main_menu(message.from_user.id)
    )


# ==========================================
# ADMIN ADD BALANCE
# ==========================================

def add_balance_for_admin(message):
    if message.from_user.id != ADMIN_ID:
        bot.send_message(
            message.chat.id,
            "âŒ Admin only.",
            reply_markup=main_menu(message.from_user.id)
        )
        return

    parts = message.text.split()

    if len(parts) != 3:
        bot.send_message(
            message.chat.id,
            "âŒ Correct format:\n\n"
            "/add USER_ID AMOUNT\n\n"
            "Example:\n"
            "/add 123456789 500",
            reply_markup=admin_menu()
        )
        return

    try:
        user_id = int(parts[1])
        amount = int(parts[2])
    except ValueError:
        bot.send_message(
            message.chat.id,
            "âŒ User ID and amount must be numbers.",
            reply_markup=admin_menu()
        )
        return

    if user_id <= 0:
        bot.send_message(
            message.chat.id,
            "âŒ Invalid User ID.",
            reply_markup=admin_menu()
        )
        return

    if amount <= 0:
        bot.send_message(
            message.chat.id,
            "âŒ Amount must be greater than â‚¹0.",
            reply_markup=admin_menu()
        )
        return

    if amount > 1000000:
        bot.send_message(
            message.chat.id,
            "âŒ Maximum allowed amount is â‚¹10,00,000.",
            reply_markup=admin_menu()
        )
        return

    try:
        with balance_lock:
            balances, orders = get_database()
            old_balance = balances.get(user_id, 0)
            new_balance = old_balance + amount

            balances[user_id] = new_balance
            save_database(balances, orders)

        bot.send_message(
            message.chat.id,
            "âœ… BALANCE ADDED\n\n"
            f"ðŸ‘¤ User ID: {user_id}\n"
            f"ðŸ’µ Added: â‚¹{amount}\n"
            f"ðŸ’° New Balance: â‚¹{new_balance}",
            reply_markup=admin_menu()
        )

        try:
            bot.send_message(
                user_id,
                "ðŸ’° Balance Added!\n\n"
                f"Added: â‚¹{amount}\n"
                f"Current Balance: â‚¹{new_balance}",
                reply_markup=main_menu(user_id)
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
            "âŒ Balance update failed.",
            reply_markup=admin_menu()
        )


@bot.message_handler(commands=["add"])
def add_balance_command(message):
    add_balance_for_admin(message)


@bot.message_handler(func=lambda m: m.text == "ðŸ’³ Add Balance")
def add_balance_button(message):
    if message.from_user.id != ADMIN_ID:
        bot.send_message(
            message.chat.id,
            "âŒ Admin only.",
            reply_markup=main_menu(message.from_user.id)
        )
        return

    bot.send_message(
        message.chat.id,
        "ðŸ’³ ADD BALANCE\n\n"
        "Use:\n"
        "/add USER_ID AMOUNT\n\n"
        "Example:\n"
        "/add 123456789 500",
        reply_markup=admin_menu()
    )


# ==========================================
# ADMIN STATISTICS
# ==========================================

def send_statistics(chat_id):
    try:
        balances, orders = get_database()

        total_users = len(balances)
        total_orders = len(orders)
        total_revenue = sum(
            o.get("price", 0) for o in orders
        )
        total_balance = sum(balances.values())

        bot.send_message(
            chat_id,
            "ðŸ“Š STORE STATISTICS\n\n"
            f"ðŸ‘¥ Total Users: {total_users}\n"
            f"ðŸ›’ Total Orders: {total_orders}\n"
            f"ðŸ’µ Total Revenue: â‚¹{total_revenue}\n"
            f"ðŸ’° User Balances: â‚¹{total_balance}",
            reply_markup=admin_menu()
        )

    except Exception:
        logging.exception("STATISTICS ERROR")
        bot.send_message(
            chat_id,
            "âŒ Could not load statistics.",
            reply_markup=admin_menu()
        )


@bot.message_handler(func=lambda m: m.text == "ðŸ“Š Statistics")
def statistics_button(message):
    if message.from_user.id != ADMIN_ID:
        bot.send_message(
            message.chat.id,
            "âŒ Admin only.",
            reply_markup=main_menu(message.from_user.id)
        )
        return

    send_statistics(message.chat.id)


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
        allowed_updates=["message", "channel_post"]
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
