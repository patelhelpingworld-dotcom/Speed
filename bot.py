import os
import threading
import logging
import time
from datetime import datetime, timedelta

import telebot
from telebot import types
from flask import Flask, request


# =========================================================
# SPEEDFISTT STORE — PREMIUM CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")

# ADMIN
ADMIN_ID = 1006157952

# TELEGRAM DATABASE CHANNEL
CHANNEL_ID = -1003892586354

# DATABASE MESSAGE IDS
BALANCE_MESSAGE_ID = 4
ORDERS_MESSAGE_ID = 8

# QR IMAGE
QR_FILE = "qr.jpg"

# Maximum stored orders
MAX_ORDERS = 40

# Branding
USER_BRAND = "⚡ This bot is made by @SpeedFistt"
OWNER_BRAND = "👑 Owner: @SpeedFistt"


# =========================================================
# PRODUCTS
# =========================================================

PRODUCTS = {
    1: {
        "name": "Digital Product A",
        "price": 100,
        "group_id": -1004494287362,
    },

    2: {
        "name": "Digital Product B",
        "price": 200,
        "group_id": -1003778035299,
    },

    3: {
        "name": "Digital Product C",
        "price": 300,
        "group_id": -1004203063772,
    },
}


# =========================================================
# BASIC CHECKS
# =========================================================

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing")

if not WEBHOOK_URL:
    raise RuntimeError("WEBHOOK_URL environment variable is missing")


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# =========================================================
# BOT
# =========================================================

bot = telebot.TeleBot(
    BOT_TOKEN,
    threaded=False
)

app = Flask(__name__)


# =========================================================
# LOCKS / TEMP STATE
# =========================================================

balance_lock = threading.Lock()
order_lock = threading.Lock()

# Add Funds temporary state
pending_funds = {}

# Prevent accidental double purchase
recent_purchases = {}


# =========================================================
# KEYBOARDS
# =========================================================

def main_menu(user_id=None):

    keyboard = types.ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    keyboard.row(
        "🛍 Products",
        "💰 Balance"
    )

    keyboard.row(
        "📜 My Orders",
        "👤 Profile"
    )

    if user_id == ADMIN_ID:
        keyboard.row(
            "👨‍💼 Admin Panel"
        )

    return keyboard


def admin_menu():

    keyboard = types.ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    keyboard.row(
        "💳 Add Balance",
        "📊 Statistics"
    )

    keyboard.row(
        "🏠 Main Menu"
    )

    return keyboard


def product_menu():

    keyboard = types.ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    keyboard.row(
        "🛒 Buy Product 1",
        "🛒 Buy Product 2"
    )

    keyboard.row(
        "🛒 Buy Product 3"
    )

    keyboard.row(
        "🏠 Main Menu"
    )

    return keyboard


def back_menu():

    keyboard = types.ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    keyboard.row(
        "🏠 Main Menu"
    )

    return keyboard


# =========================================================
# INLINE JOIN BUTTON
# =========================================================

def join_button(invite_link):

    keyboard = types.InlineKeyboardMarkup()

    keyboard.add(
        types.InlineKeyboardButton(
            "🟢 JOIN GROUP 🟢",
            url=invite_link
        )
    )

    return keyboard


# =========================================================
# BALANCE DATABASE
# =========================================================

def parse_balances(text):

    balances = {}

    for line in text.splitlines():

        line = line.strip()

        if not line.startswith("USER:"):
            continue

        try:

            parts = line.split("|")

            user_id = int(
                parts[0].split(":", 1)[1].strip()
            )

            balance = int(
                float(
                    parts[1].split(":", 1)[1].strip()
                )
            )

            balances[user_id] = balance

        except Exception:
            continue

    return balances


def format_balances(balances):

    lines = [
        "💰 SPEEDFISTT BALANCE DATABASE",
        ""
    ]

    if not balances:

        lines.append(
            "No users registered yet."
        )

    else:

        for user_id in sorted(balances):

            lines.append(
                f"USER: {user_id} | BALANCE: {balances[user_id]}"
            )

    return "\n".join(lines)


def read_balance_message():

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

    text = format_balances(balances)

    bot.edit_message_text(
        text=text,
        chat_id=CHANNEL_ID,
        message_id=BALANCE_MESSAGE_ID
    )


# =========================================================
# ORDERS DATABASE
# =========================================================

def parse_orders(text):

    orders = []

    for line in text.splitlines():

        line = line.strip()

        if not line.startswith("ORDER|"):
            continue

        try:

            parts = line.split("|")

            if len(parts) < 8:
                continue

            order = {
                "order_id": parts[1],
                "user_id": int(parts[2]),
                "product_id": int(parts[3]),
                "product_name": parts[4],
                "price": int(parts[5]),
                "date": parts[6],
                "status": parts[7],
            }

            orders.append(order)

        except Exception:
            continue

    return orders


def format_orders(orders):

    lines = [
        "📜 SPEEDFISTT ORDERS DATABASE",
        ""
    ]

    if not orders:

        lines.append(
            "No orders yet."
        )

    else:

        for order in orders[-MAX_ORDERS:]:

            lines.append(
                "ORDER|"
                f"{order['order_id']}|"
                f"{order['user_id']}|"
                f"{order['product_id']}|"
                f"{order['product_name']}|"
                f"{order['price']}|"
                f"{order['date']}|"
                f"{order['status']}"
            )

    return "\n".join(lines)


def read_orders_message():

    forwarded = bot.forward_message(
        chat_id=ADMIN_ID,
        from_chat_id=CHANNEL_ID,
        message_id=ORDERS_MESSAGE_ID
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


def get_orders():

    text = read_orders_message()

    return parse_orders(text)


def save_orders(orders):

    orders = orders[-MAX_ORDERS:]

    text = format_orders(orders)

    bot.edit_message_text(
        text=text,
        chat_id=CHANNEL_ID,
        message_id=ORDERS_MESSAGE_ID
    )


def add_order(order):

    with order_lock:

        orders = get_orders()

        orders.append(order)

        save_orders(orders)


# =========================================================
# ORDER ID
# =========================================================

def generate_order_id():

    timestamp = int(time.time())

    return f"SF{timestamp}"


# =========================================================
# REGISTER USER
# =========================================================

def register_user(user_id):

    with balance_lock:

        balances = get_balances()

        if user_id not in balances:

            balances[user_id] = 0

            save_balances(balances)


# =========================================================
# PREMIUM WELCOME
# =========================================================

def send_welcome(chat_id, user_id):

    text = (
        "╔══════════════════════╗\n"
        "     ⚡ SPEEDFISTT STORE\n"
        "╚══════════════════════╝\n\n"

        "🚀 Welcome to your premium digital store.\n\n"

        "🛍 Explore products\n"
        "💰 Manage your balance\n"
        "📜 Track your orders\n"
        "🔐 Get instant group access\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{USER_BRAND}"
    )

    bot.send_message(
        chat_id,
        text,
        reply_markup=main_menu(user_id)
    )


# =========================================================
# START
# =========================================================

@bot.message_handler(commands=["start"])
def start_command(message):

    user_id = message.from_user.id

    try:

        register_user(user_id)

        pending_funds.pop(user_id, None)

        send_welcome(
            message.chat.id,
            user_id
        )

    except Exception:

        logging.exception(
            "START ERROR"
        )

        bot.send_message(
            message.chat.id,
            "❌ Store temporarily unavailable.\n"
            "Please try again."
        )


# =========================================================
# BALANCE
# =========================================================

@bot.message_handler(commands=["balance"])
def balance_command(message):

    user_id = message.from_user.id

    try:

        balances = get_balances()

        balance = balances.get(
            user_id,
            0
        )

        text = (
            "╔══════════════════════╗\n"
            "        💰 BALANCE\n"
            "╚══════════════════════╝\n\n"

            f"💵 Available Balance\n"
            f"₹{balance}\n\n"

            "━━━━━━━━━━━━━━━━━━━━\n"
            "💳 Need more balance?\n"
            "Use the Add Funds option.\n\n"

            f"{USER_BRAND}"
        )

        bot.send_message(
            message.chat.id,
            text,
            reply_markup=main_menu(user_id)
        )

    except Exception:

        logging.exception(
            "BALANCE ERROR"
        )

        bot.send_message(
            message.chat.id,
            "❌ Could not check balance."
        )


# =========================================================
# PRODUCTS
# =========================================================

def show_products(chat_id, user_id):

    text = (
        "╔══════════════════════╗\n"
        "       🛍 STORE\n"
        "╚══════════════════════╝\n\n"

        "✨ Premium Digital Products\n\n"

        "① Digital Product A\n"
        "   💵 ₹100\n"
        "   ⚡ Instant delivery\n\n"

        "② Digital Product B\n"
        "   💵 ₹200\n"
        "   ⚡ Instant delivery\n\n"

        "③ Digital Product C\n"
        "   💵 ₹300\n"
        "   ⚡ Instant delivery\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "👇 Select a product to purchase.\n\n"

        f"{USER_BRAND}"
    )

    bot.send_message(
        chat_id,
        text,
        reply_markup=product_menu()
    )


@bot.message_handler(commands=["products"])
def products_command(message):

    show_products(
        message.chat.id,
        message.from_user.id
    )


# =========================================================
# CREATE INVITE LINK
# =========================================================

def create_product_invite(product_id):

    product = PRODUCTS[product_id]

    group_id = product["group_id"]

    expire_timestamp = int(
        (datetime.now() + timedelta(hours=24)).timestamp()
    )

    invite = bot.create_chat_invite_link(
        chat_id=group_id,
        name=f"SpeedFistt Product {product_id}",
        expire_date=expire_timestamp,
        member_limit=1
    )

    return invite.invite_link


# =========================================================
# PURCHASE
# =========================================================

def purchase_product(message, product_id):

    user_id = message.from_user.id

    if product_id not in PRODUCTS:

        bot.send_message(
            message.chat.id,
            "❌ Product not found."
        )

        return

    product = PRODUCTS[product_id]

    price = product["price"]

    product_name = product["name"]

    # -----------------------------------------------------
    # DOUBLE CLICK PROTECTION
    # -----------------------------------------------------

    key = (
        user_id,
        product_id
    )

    now = time.time()

    last_purchase = recent_purchases.get(
        key,
        0
    )

    if now - last_purchase < 5:

        bot.send_message(
            message.chat.id,
            "⏳ Please wait a few seconds before purchasing again."
        )

        return

    recent_purchases[key] = now

    try:

        # -------------------------------------------------
        # CHECK BALANCE FIRST
        # -------------------------------------------------

        with balance_lock:

            balances = get_balances()

            current_balance = balances.get(
                user_id,
                0
            )

            if current_balance < price:

                missing = price - current_balance

                text = (
                    "╔══════════════════════╗\n"
                    "       💳 LOW BALANCE\n"
                    "╚══════════════════════╝\n\n"

                    f"🛍 Product: {product_name}\n"
                    f"💵 Price: ₹{price}\n"
                    f"💰 Your Balance: ₹{current_balance}\n"
                    f"📉 Required: ₹{missing} more\n\n"

                    "Please add funds and try again.\n\n"

                    f"{USER_BRAND}"
                )

                bot.send_message(
                    message.chat.id,
                    text,
                    reply_markup=main_menu(user_id)
                )

                return

        # -------------------------------------------------
        # GENERATE INVITE BEFORE DEDUCTION
        # -------------------------------------------------

        try:

            invite_link = create_product_invite(
                product_id
            )

        except Exception:

            logging.exception(
                "INVITE CREATION ERROR"
            )

            bot.send_message(
                message.chat.id,
                "❌ Delivery system is temporarily unavailable.\n\n"
                "Your balance has NOT been deducted.\n"
                "Please try again later."
            )

            return

        # -------------------------------------------------
        # DEDUCT BALANCE
        # -------------------------------------------------

        with balance_lock:

            balances = get_balances()

            current_balance = balances.get(
                user_id,
                0
            )

            if current_balance < price:

                bot.send_message(
                    message.chat.id,
                    "❌ Balance changed while processing.\n"
                    "Please try again."
                )

                return

            new_balance = current_balance - price

            balances[user_id] = new_balance

            save_balances(balances)

        # -------------------------------------------------
        # CREATE ORDER
        # -------------------------------------------------

        order_id = generate_order_id()

        date_text = datetime.now().strftime(
            "%Y-%m-%d %H:%M"
        )

        order = {
            "order_id": order_id,
            "user_id": user_id,
            "product_id": product_id,
            "product_name": product_name,
            "price": price,
            "date": date_text,
            "status": "DELIVERED",
        }

        try:

            add_order(order)

        except Exception:

            logging.exception(
                "ORDER SAVE ERROR"
            )

            # Restore balance if order database failed
            with balance_lock:

                balances = get_balances()

                balances[user_id] = (
                    balances.get(user_id, 0)
                    + price
                )

                save_balances(balances)

            bot.send_message(
                message.chat.id,
                "❌ Order could not be completed.\n"
                "Your balance has been restored."
            )

            return

        # -------------------------------------------------
        # SUCCESS MESSAGE
        # -------------------------------------------------

        text = (
            "╔══════════════════════╗\n"
            "     ✅ ORDER COMPLETE\n"
            "╚══════════════════════╝\n\n"

            "🎉 Your purchase was successful!\n\n"

            f"🛍 Product\n"
            f"{product_name}\n\n"

            f"💵 Paid: ₹{price}\n"
            f"💰 Remaining: ₹{new_balance}\n\n"

            f"🧾 Order ID\n"
            f"`{order_id}`\n\n"

            "🔐 Your access link is ready.\n"
            "⚠️ Link can be used only once and expires in 24 hours.\n\n"

            f"{USER_BRAND}"
        )

        bot.send_message(
            message.chat.id,
            text,
            parse_mode="Markdown",
            reply_markup=join_button(
                invite_link
            )
        )

        # -------------------------------------------------
        # ADMIN LOG
        # -------------------------------------------------

        try:

            bot.send_message(
                ADMIN_ID,
                "╔══════════════════════╗\n"
                "        🛒 NEW ORDER\n"
                "╚══════════════════════╝\n\n"

                f"🧾 Order: {order_id}\n"
                f"👤 User ID: {user_id}\n"
                f"🛍 Product: {product_name}\n"
                f"💵 Amount: ₹{price}\n"
                f"📅 {date_text}\n"
                f"📦 Status: DELIVERED\n\n"

                f"{OWNER_BRAND}"
            )

        except Exception:
            pass

    except Exception:

        logging.exception(
            "PURCHASE ERROR"
        )

        bot.send_message(
            message.chat.id,
            "❌ Purchase failed.\n"
            "Please try again later."
        )


# =========================================================
# /BUY COMMAND
# =========================================================

@bot.message_handler(commands=["buy"])
def buy_command(message):

    parts = message.text.split()

    if len(parts) != 2:

        bot.send_message(
            message.chat.id,
            "❌ Invalid product."
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

    purchase_product(
        message,
        product_id
    )


# =========================================================
# MY ORDERS
# =========================================================

def show_my_orders(chat_id, user_id):

    try:

        orders = get_orders()

        user_orders = [
            order
            for order in orders
            if order["user_id"] == user_id
        ]

        if not user_orders:

            text = (
                "╔══════════════════════╗\n"
                "       📜 MY ORDERS\n"
                "╚══════════════════════╝\n\n"

 
