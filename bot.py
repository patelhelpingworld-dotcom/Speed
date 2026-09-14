import os
import threading
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


# ==========================================
# DATABASE
# ==========================================

def parse_database(text):
    balances = {}
    orders = []

    for line in text.splitlines():
        line = line.strip()

        if line.startswith("USER:") and "|" in line:
            try:
                user_part, balance_part = line.split("|", 1)

                user_id = int(
                    user_part.split(":", 1)[1].strip()
                )

                balance = int(
                    float(
                        balance_part.split(":", 1)[1].strip()
                    )
                )

                balances[user_id] = balance

            except (ValueError, IndexError):
                pass

        elif line.startswith("ORDER:") and "|" in line:
            try:
                parts = line.split("|")
                order = {}

                for part in parts:
                    key, value = part.split(":", 1)
                    order[key.strip().lower()] = value.strip()

                order["user"] = int(order["user"])
                order["price"] = int(float(order["price"]))

                orders.append(order)

            except (ValueError, IndexError):
                pass

    return balances, orders


def format_database(balances, orders):
    lines = [
        "SPEEDFISTT STORE DATABASE",
        "",
        "STATISTICS",
        f"USERS: {len(balances)}",
        f"ORDERS: {len(orders)}",
        f"REVENUE: ₹{sum(o.get('price', 0) for o in orders)}",
        "",
        "BALANCES"
    ]

    if balances:
        for user_id in sorted(balances):
            lines.append(
                f"USER: {user_id} | BALANCE: {balances[user_id]}"
            )
    else:
        lines.append("No users registered yet.")

    lines.extend([
        "",
        "ORDERS"
    ])

    if orders:
        for order in orders[-50:]:
            lines.append(
                f"ORDER: {order.get('id', 'N/A')} | "
                f"USER: {order.get('user', 0)} | "
                f"PRODUCT: {order.get('product', 'Unknown')} | "
                f"PRICE: {order.get('price', 0)} | "
                f"TIME: {order.get('time', 'N/A')}"
            )
    else:
        lines.append("No orders yet.")

    text = "\n".join(lines)

    if len(text) > 3900:
        orders = orders[-20:]
        return format_database(balances, orders)

    return text


def read_database():
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
    text = read_database()
    return parse_database(text)


def save_database(balances, orders):
    text = format_database(
        balances,
        orders
    )

    bot.edit_message_text(
        text=text,
        chat_id=CHANNEL_ID,
        message_id=BALANCE_MESSAGE_ID
    )


# ==========================================
# KEYBOARDS
# ==========================================

def main_menu(user_id):
    keyboard = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=2
    )

    keyboard.add(
        types.KeyboardButton("🛍 Products"),
        types.KeyboardButton("💰 Balance")
    )

    keyboard.add(
        types.KeyboardButton("📜 My Orders"),
        types.KeyboardButton("👤 Profile")
    )

    if user_id == ADMIN_ID:
        keyboard.add(
            types.KeyboardButton("👨‍💼 Admin Panel")
        )

    return keyboard


def admin_menu():
    keyboard = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=2
    )

    keyboard.add(
        types.KeyboardButton("💳 Add Balance"),
        types.KeyboardButton("📊 Statistics")
    )

    keyboard.add(
        types.KeyboardButton("🏠 Main Menu")
    )

    return keyboard


# ==========================================
# CHANNEL DEBUG
# ==========================================

@bot.channel_post_handler(func=lambda message: True)
def channel_post_debug(message):
    print(
        f"CHANNEL FOUND | chat_id={message.chat.id} | "
        f"message_id={message.message_id} | "
        f"text={message.text}"
    )


# ==========================================
# START
# ==========================================

@bot.message_handler(commands=["start"])
def start_command(message):
    user_id = message.from_user.id

    try:
        with balance_lock:
            balances, orders = get_database()

            if user_id not in balances:
                balances[user_id] = 0
                save_database(
                    balances,
                    orders
                )

        bot.send_message(
            message.chat.id,
            "👋 Welcome to SpeedFistt Store!\n\n"
            "Choose an option from the menu.",
            reply_markup=main_menu(user_id)
        )

    except Exception:
        print("START ERROR")

        bot.send_message(
            message.chat.id,
            "❌ Store setup error.\n"
            "Please contact admin."
        )


# ==========================================
# MAIN MENU
# ==========================================

@bot.message_handler(
    func=lambda message: message.text == "🏠 Main Menu"
)
def main_menu_button(message):
    bot.send_message(
        message.chat.id,
        "🏠 Main Menu\n\n"
        "Choose an option below.",
        reply_markup=main_menu(
            message.from_user.id
        )
    )


# ==========================================
# BALANCE
# ==========================================

def show_balance(message):
    try:
        balances, _ = get_database()

        balance = balances.get(
            message.from_user.id,
            0
        )

        bot.send_message(
            message.chat.id,
            "💰 Balance\n\n"
            f"Available Balance: ₹{balance}",
            reply_markup=main_menu(
                message.from_user.id
            )
        )

    except Exception:
        print("BALANCE ERROR")

        bot.send_message(
            message.chat.id,
            "❌ Could not check balance.",
            reply_markup=main_menu(
                message.from_user.id
            )
        )


@bot.message_handler(commands=["balance"])
def balance_command(message):
    show_balance(message)


@bot.message_handler(
    func=lambda message: message.text == "💰 Balance"
)
def balance_button(message):
    show_balance(message)


# ==========================================
# PRODUCTS
# ==========================================

def show_products(message):
    text = "🛍 SPEEDFISTT STORE\n\n"

    for product_id, product in PRODUCTS.items():
        text += (
            f"{product_id}️⃣ {product['name']}\n"
            f"💵 Price: ₹{product['price']}\n"
            f"🛒 Buy: /buy {product_id}\n\n"
        )

    bot.send_message(
        message.chat.id,
        text,
        reply_markup=main_menu(
            message.from_user.id
        )
    )


@bot.message_handler(commands=["products"])
def products_command(message):
    show_products(message)


@bot.message_handler(
    func=lambda message: message.text == "🛍 Products"
)
def products_button(message):
    show_products(message)


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
            "/buy 2",
            reply_markup=main_menu(
                message.from_user.id
            )
        )
        return

    try:
        product_id = int(parts[1])

    except ValueError:
        bot.send_message(
            message.chat.id,
            "❌ Invalid product.",
            reply_markup=main_menu(
                message.from_user.id
            )
        )
        return

    if product_id not in PRODUCTS:
        bot.send_message(
            message.chat.id,
            "❌ Product not found.",
            reply_markup=main_menu(
                message.from_user.id
            )
        )
        return

    product = PRODUCTS[product_id]

    user_id = message.from_user.id
    price = product["price"]
    product_name = product["name"]

    try:
        with balance_lock:
            balances, orders = get_database()

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
                    f"Your balance: ₹{current_balance}",
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
                "time": datetime.now().strftime(
                    "%Y-%m-%d %H:%M"
                )
            }

            orders.append(order)

            save_database(
                balances,
                orders
            )

        bot.send_message(
            message.chat.id,
            "✅ PURCHASE SUCCESSFUL!\n\n"
            f"🧾 Order ID: #{order['id']}\n"
            f"🛍 Product: {product_name}\n"
            f"💵 Price: ₹{price}\n"
            f"💰 Remaining Balance: ₹{new_balance}",
            reply_markup=main_menu(user_id)
        )

    except Exception:
        print("PURCHASE ERROR")

        bot.send_message(
            message.chat.id,
            "❌ Purchase failed.",
            reply_markup=main_menu(user_id)
        )


# ==========================================
# ORDERS
# ==========================================

def show_orders(message):
    try:
        _, orders = get_database()

        user_id = message.from_user.id

        user_orders = [
            order
            for order in orders
            if order.get("user") == user_id
        ]

        if not user_orders:
            text = (
                "📜 My Orders\n\n"
                "No purchases yet."
            )

        else:
            text = "📜 My Orders\n\n"

            for order in reversed(
                user_orders[-20:]
            ):
                text += (
                    f"🧾 #{order.get('id', 'N/A')}\n"
                    f"🛍 {order.get('product', 'Unknown')}\n"
                    f"💵 ₹{order.get('price', 0)}\n"
                    f"🕐 {order.get('time', 'N/A')}\n\n"
                )

        bot.send_message(
            message.chat.id,
            text,
            reply_markup=main_menu(user_id)
        )

    except Exception:
        print("ORDERS ERROR")

        bot.send_message(
            message.chat.id,
            "❌ Could not load orders.",
            reply_markup=main_menu(
                message.from_user.id
            )
        )


@bot.message_handler(commands=["orders"])
def orders_command(message):
    show_orders(message)


@bot.message_handler(
    func=lambda message: message.text == "📜 My Orders"
)
def orders_button(message):
    show_orders(message)


# ==========================================
# PROFILE
# ==========================================

def show_profile(message):
    try:
        balances, orders = get_database()

        user = message.from_user

        balance = balances.get(
            user.id,
            0
        )

        total_orders = sum(
            1
            for order in orders
            if order.get("user") == user.id
        )

        username = (
            f"@{user.username}"
            if user.username
            else "Not set"
        )

        bot.send_message(
            message.chat.id,
            "👤 Profile\n\n"
            f"🆔 User ID: {user.id}\n"
            f"👤 Username: {username}\n"
            f"💰 Balance: ₹{balance}\n"
            f"📜 Orders: {total_orders}",
            reply_markup=main_menu(user.id)
        )

    except Exception:
        print("PROFILE ERROR")

        bot.send_message(
            message.chat.id,
            "❌ Could not load profile.",
            reply_markup=main_menu(
                message.from_user.id
            )
        )


@bot.message_handler(commands=["profile"])
def profile_command(message):
    show_profile(message)


@bot.message_handler(
    func=lambda message: message.text == "👤 Profile"
)
def profile_button(message):
    show_profile(message)


# ==========================================
# ADMIN PANEL
# ==========================================

@bot.message_handler(
    func=lambda message: message.text == "👨‍💼 Admin Panel"
)
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        bot.send_message(
            message.chat.id,
            "❌ Admin only.",
            reply_markup=main_menu(
                message.from_user.id
            )
        )
        return

    bot.send_message(
        message.chat.id,
        "👨‍💼 Admin Panel\n\n"
        "Choose an option below.",
        reply_markup=admin_menu()
    )


# ==========================================
# ADD BALANCE
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
            "❌ User ID and amount must be numbers.",
            reply_markup=admin_menu()
        )
        return

    if user_id <= 0:
        bot.send_message(
            message.chat.id,
            "❌ Invalid User ID.",
            reply_markup=admin_menu()
        )
        return

    if amount <= 0:
        bot.send_message(
            message.chat.id,
            "❌ Amount must be greater than ₹0.",
            reply_markup=admin_menu()
        )
        return

    if amount > 1000000:
        bot.send_message(
            message.chat.id,
            "❌ Maximum allowed amount is ₹10,00,000.",
            reply_markup=admin_menu()
        )
        return

    try:
        with balance_lock:
            balances, orders = get_database()

            old_balance = balances.get(
                user_id,
                0
            )

            new_balance = old_balance + amount

            balances[user_id] = new_balance

            save_database(
                balances,
                orders
            )

        bot.send_message(
            message.chat.id,
            "✅ BALANCE ADDED\n\n"
            f"👤 User ID: {user_id}\n"
            f"💵 Added: ₹{amount}\n"
            f"💰 New Balance: ₹{new_balance}",
            reply_markup=admin_menu()
        )

        try:
            bot.send_message(
                user_id,
                "💰 Balance Added!\n\n"
                f"Added: ₹{amount}\n"
                f"Current Balance: ₹{new_balance}",
                reply_markup=main_menu(user_id)
            )

        except Exception:
            pass

    except Exception:
        print("ADD BALANCE ERROR")

        bot.send_message(
            message.chat.id,
            "❌ Balance update failed.",
            reply_markup=admin_menu()
        )


@bot.message_handler(
    func=lambda message: message.text == "💳 Add Balance"
)
def add_balance_button(message):
    if message.from_user.id != ADMIN_ID:
        bot.send_message(
            message.chat.id,
            "❌ Admin only."
        )
        return

    bot.send_message(
        message.chat.id,
        "💳 Add Balance\n\n"
        "Use:\n"
        "/add USER_ID AMOUNT\n\n"
        "Example:\n"
        "/add 123456789 500",
        reply_markup=admin_menu()
    )


# ==========================================
# STATISTICS
# ==========================================

@bot.message_handler(
    func=lambda message: message.text == "📊 Statistics"
)
def statistics_button(message):
    if message.from_user.id != ADMIN_ID:
        bot.send_message(
            message.chat.id,
            "❌ Admin only.",
            reply_markup=main_menu(
                message.from_user.id
            )
        )
        return

    try:
        balances, orders = get_database()

        total_users = len(balances)

        total_orders = len(orders)

        total_revenue = sum(
            order.get("price", 0)
            for order in orders
        )

        total_balance = sum(
            balances.values()
        )

        bot.send_message(
            message.chat.id,
            "📊 Store Statistics\n\n"
            f"👥 Total Users: {total_users}\n"
            f"🛒 Total Orders: {total_orders}\n"
            f"💵 Total Revenue: ₹{total_revenue}\n"
            f"💰 User Balances: ₹{total_balance}",
            reply_markup=admin_menu()
        )

    except Exception:
        print("STATISTICS ERROR")

        bot.send_message(
            message.chat.id,
            "❌ Could not load statistics.",
            reply_markup=admin_menu()
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

        update = telebot.types.Update.de_json(data)

        bot.process_new_updates(
            [update]
        )

        return "OK", 200

    except Exception:
        print("WEBHOOK ERROR")
        return "ERROR", 500


# ==========================================
# SET WEBHOOK
# ==========================================

def setup_webhook():
    webhook_url = f"{WEBHOOK_URL}/webhook"

    bot.remove_webhook()

    bot.set_webhook(
        url=webhook_url,
        allowed_updates=[
            "message",
            "channel_post"
        ]
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
