import os
import threading
import time
import logging
from datetime import datetime, timedelta

import telebot
from telebot import types
from flask import Flask, request


# =========================================================
# ⚡ BGMI HACK STORE — PREMIUM HACKS
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")

# 👑 ADMIN
ADMIN_ID = 1006157952

# 📦 TELEGRAM DATABASE CHANNEL
CHANNEL_ID = -1003892586354

# 💰 BALANCE DATABASE MESSAGE
BALANCE_MESSAGE_ID = 4

# 📜 ORDERS DATABASE MESSAGE
ORDERS_MESSAGE_ID = 8

# 🖼️ PAYMENT QR
QR_FILE = "qr.jpg"

# Maximum orders stored in Telegram database
MAX_ORDERS = 40

# =========================================================
# BRANDING
# =========================================================

USER_BRAND = "⚡ This bot is made by @SpeedFistt"
OWNER_BRAND = "👑 Owner: @SpeedFistt"


# =========================================================
# 🛍 PRODUCTS
# =========================================================

PRODUCTS = {

    1: {
        "name": "OBB & FILES",
        "price": 299,
        "group_id": -1004494287362
    },

    2: {
        "name": "SAFE HACK (1-month)",
        "price": 499,
        "group_id": -1003778035299
    },

    3: {
        "name": "SAFE HACK (full season)",
        "price": 799,
        "group_id": -1004203063772
    }

}


# =========================================================
# CHECK CONFIG
# =========================================================

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN environment variable is missing"
    )

if not WEBHOOK_URL:
    raise RuntimeError(
        "WEBHOOK_URL environment variable is missing"
    )


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
# LOCKS
# =========================================================

balance_lock = threading.Lock()
order_lock = threading.Lock()


# =========================================================
# TEMPORARY STATES
# =========================================================

# Example:
# pending_funds[user_id] = {
#     "stage": "amount"
# }

pending_funds = {}

# Duplicate-click protection
recent_purchases = {}


# =========================================================
# 🏠 MAIN MENU
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
        "💳 Add Funds",
        "📜 My Orders"
    )

    keyboard.row(
        "👤 Profile"
    )

    # Admin button ONLY for owner
    if user_id == ADMIN_ID:

        keyboard.row(
            "👨‍💼 Admin Panel"
        )

    return keyboard


# =========================================================
# 👑 ADMIN MENU
# =========================================================

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


# =========================================================
# 🛍 PRODUCT MENU
# =========================================================

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


# =========================================================
# BACK MENU
# =========================================================

def back_menu():

    keyboard = types.ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    keyboard.row(
        "🏠 Main Menu"
    )

    return keyboard


# =========================================================
# 🟢 INLINE JOIN BUTTON
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
# 💰 BALANCE DATABASE
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
                parts[0]
                .split(":", 1)[1]
                .strip()
            )

            balance = int(
                float(
                    parts[1]
                    .split(":", 1)[1]
                    .strip()
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

    new_text = format_balances(
        balances
    )

    bot.edit_message_text(
        text=new_text,
        chat_id=CHANNEL_ID,
        message_id=BALANCE_MESSAGE_ID
    )


# =========================================================
# 📜 ORDERS DATABASE
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

                "user_id": int(
                    parts[2]
                ),

                "product_id": int(
                    parts[3]
                ),

                "product_name": parts[4],

                "price": int(
                    parts[5]
                ),

                "date": parts[6],

                "status": parts[7]
            }

            orders.append(
                order
            )

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

    bot.edit_message_text(
        text=format_orders(orders),
        chat_id=CHANNEL_ID,
        message_id=ORDERS_MESSAGE_ID
    )


def add_order(order):

    with order_lock:

        orders = get_orders()

        orders.append(
            order
        )

        save_orders(
            orders
        )


# =========================================================
# 🧾 ORDER ID
# =========================================================

def generate_order_id():

    return (
        "SF"
        + str(
            int(
                time.time()
                * 1000
            )
        )[-10:]
    )


# =========================================================
# 👤 REGISTER USER
# =========================================================

def register_user(user_id):

    with balance_lock:

        balances = get_balances()

        if user_id not in balances:

            balances[user_id] = 0

            save_balances(
                balances
            )


# =========================================================
# ⚡ PREMIUM WELCOME
# =========================================================

def send_welcome(
    chat_id,
    user_id
):

    text = (
        "╔════════════════════════╗\n"
        "      ⚡ BGMI HACK STORE\n"
        "╚════════════════════════╝\n\n"

        "👋 Welcome to the premium store!\n\n"

        "🛍 Digital Products\n"
        "⚡ Fast & Secure Delivery\n"
        "💳 Easy Balance System\n"
        "📜 Order History\n"
        "🔐 Private Group Access\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"

        "👇 Choose an option below\n\n"

        f"{USER_BRAND}"
    )

    bot.send_message(
        chat_id,
        text,
        reply_markup=main_menu(
            user_id
        )
    )


# =========================================================
# /START
# =========================================================

@bot.message_handler(
    commands=["start"]
)
def start_command(message):

    user_id = message.from_user.id

    try:

        register_user(
            user_id
        )

        pending_funds.pop(
            user_id,
            None
        )

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
            "❌ Store setup error.\n\n"
            "Please try again later."
        )


# =========================================================
# 💰 BALANCE
# =========================================================

@bot.message_handler(
    commands=["balance"]
)
def balance_command(message):

    user_id = message.from_user.id

    try:

        balances = get_balances()

        balance = balances.get(
            user_id,
            0
        )

        text = (
            "╔════════════════════════╗\n"
            "          💰 BALANCE\n"
            "╚════════════════════════╝\n\n"

            "💵 Available Balance\n\n"

            f"      ₹{balance}\n\n"

            "━━━━━━━━━━━━━━━━━━━━━━\n"

            "💳 Need more balance?\n"
            "Use 💳 Add Funds.\n\n"

            f"{USER_BRAND}"
        )

        bot.send_message(
            message.chat.id,
            text,
            reply_markup=main_menu(
                user_id
            )
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
# 🛍 PRODUCTS
# =========================================================

def show_products(
    chat_id,
    user_id
):

    text = (
        "╔════════════════════════╗\n"
        "        🛍 BGMI HACK STORE\n"
        "╚════════════════════════╝\n\n"

        "✨ PREMIUM DIGITAL PRODUCTS\n\n"

        "① OBB & FILES\n"
        "   💵 Price: ₹299\n"
        "   ⚡ Instant Access\n\n"

        "② SAFE HACK (1-month)\n"
        "   💵 Price: ₹499\n"
        "   ⚡ Instant Access\n\n"

        "③ SAFE HACK (full season)\n"
        "   💵 Price: ₹799\n"
        "   ⚡ Instant Access\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"

        "🔐 Private Group Access\n"
        "🟢 One-Time Invite\n"
        "⏱️ 24 Hours Validity\n\n"

        "👇 Select your product below.\n\n"

        f"{USER_BRAND}"
    )

    bot.send_message(
        chat_id,
        text,
        reply_markup=product_menu()
    )


@bot.message_handler(
    commands=["products"]
)
def products_command(message):

    show_products(
        message.chat.id,
        message.from_user.id
    )


# =========================================================
# 🔐 CREATE INVITE LINK
# =========================================================

def create_product_invite(
    product_id
):

    product = PRODUCTS[
        product_id
    ]

    group_id = product[
        "group_id"
    ]

    expire_timestamp = int(
        (
            datetime.now()
            + timedelta(hours=24)
        ).timestamp()
    )

    invite = bot.create_chat_invite_link(

        chat_id=group_id,

        name=(
            f"SpeedFistt "
            f"Product {product_id}"
        ),

        expire_date=expire_timestamp,

        member_limit=1
    )

    return invite.invite_link


# =========================================================
# 🛒 PURCHASE
# =========================================================

def purchase_product(
    message,
    product_id
):

    user_id = message.from_user.id

    if product_id not in PRODUCTS:

        bot.send_message(
            message.chat.id,
            "❌ Product not found."
        )

        return

    product = PRODUCTS[
        product_id
    ]

    price = product[
        "price"
    ]

    product_name = product[
        "name"
    ]

    # =====================================================
    # DOUBLE CLICK PROTECTION
    # =====================================================

    purchase_key = (
        user_id,
        product_id
    )

    now = time.time()

    last_time = recent_purchases.get(
        purchase_key,
        0
    )

    if now - last_time < 5:

        bot.send_message(
            message.chat.id,
            "⏳ Please wait a few seconds."
        )

        return

    recent_purchases[
        purchase_key
    ] = now

    try:

        # =================================================
        # CHECK BALANCE
        # =================================================

        with balance_lock:

            balances = get_balances()

            current_balance = balances.get(
                user_id,
                0
            )

            if current_balance < price:

                required = (
                    price
                    - current_balance
                )

                text = (
                    "╔════════════════════════╗\n"
                    "       💳 LOW BALANCE\n"
                    "╚════════════════════════╝\n\n"

                    f"🛍 {product_name}\n"
                    f"💵 Price: ₹{price}\n"
                    f"💰 Balance: ₹{current_balance}\n"
                    f"📉 Need: ₹{required} more\n\n"

                    "Please add funds first.\n\n"

                    f"{USER_BRAND}"
                )

                bot.send_message(
                    message.chat.id,
                    text,
                    reply_markup=main_menu(
                        user_id
                    )
                )

                return

        # =================================================
        # GENERATE DELIVERY LINK
        # =================================================

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
                "💰 Your balance was NOT deducted.\n\n"
                "Please try again later."
            )

            return

        # =================================================
        # DEDUCT BALANCE
        # =================================================

        with balance_lock:

            balances = get_balances()

            current_balance = balances.get(
                user_id,
                0
            )

            if current_balance < price:

                bot.send_message(
                    message.chat.id,
                    "❌ Balance changed.\n"
                    "Please try again."
                )

                return

            new_balance = (
                current_balance
                - price
            )

            balances[user_id] = (
                new_balance
            )

            save_balances(
                balances
            )

        # =================================================
        # CREATE ORDER
        # =================================================

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

            "status": "DELIVERED"
        }

        try:

            add_order(
                order
            )

        except Exception:

            logging.exception(
                "ORDER SAVE ERROR"
            )

            # Restore balance
            with balance_lock:

                balances = get_balances()

                balances[user_id] = (
                    balances.get(
                        user_id,
                        0
                    )
                    + price
                )

                save_balances(
                    balances
                )

            bot.send_message(
                message.chat.id,
                "❌ Order could not be completed.\n\n"
                "💰 Your balance has been restored."
            )

            return

        # =================================================
        # SUCCESS
        # =================================================

        success_text = (
            "╔════════════════════════╗\n"
            "       ✅ ORDER COMPLETE\n"
            "╚════════════════════════╝\n\n"

            "🎉 Purchase successful!\n\n"

            "🛍 PRODUCT\n"
            f"{product_name}\n\n"

            "💵 PAID\n"
            f"₹{price}\n\n"

            "💰 REMAINING BALANCE\n"
            f"₹{new_balance}\n\n"

            "━━━━━━━━━━━━━━━━━━━━━━\n"

            "🧾 ORDER ID\n"
            f"`{order_id}`\n\n"

            "🔐 ACCESS READY\n"
            "Your private group access is ready below.\n\n"

            "⚠️ One-time use\n"
            "⏱️ Valid for 24 hours\n\n"

            f"{USER_BRAND}"
        )

        bot.send_message(
            message.chat.id,
            success_text,
            parse_mode="Markdown",
            reply_markup=join_button(
                invite_link
            )
        )

        # =================================================
        # ADMIN ORDER LOG
        # =================================================

        try:

            bot.send_message(

                ADMIN_ID,

                "╔════════════════════════╗\n"
                "         🛒 NEW ORDER\n"
                "╚════════════════════════╝\n\n"

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
            "❌ Purchase failed.\n\n"
            "Please try again later."
        )


# =========================================================
# /BUY
# =========================================================

@bot.message_handler(
    commands=["buy"]
)
def buy_command(message):

    parts = message.text.split()

    if len(parts) != 2:

        bot.send_message(
            message.chat.id,
            "❌ Invalid product."
        )

        return

    try:

        product_id = int(
            parts[1]
        )

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
# 📜 MY ORDERS
# =========================================================

def show_my_orders(
    chat_id,
    user_id
):

    try:

        orders = get_orders()

        user_orders = [

            order

            for order in orders

            if order["user_id"] == user_id

        ]

        if not user_orders:

            text = (
                "╔════════════════════════╗\n"
                "         📜 MY ORDERS\n"
                "╚════════════════════════╝\n\n"

                "📦 No orders found.\n\n"

                "🛍 Visit Products to start shopping.\n\n"

                f"{USER_BRAND}"
            )

            bot.send_message(
                chat_id,
                text,
                reply_markup=main_menu(
                    user_id
                )
            )

            return

        user_orders = user_orders[-10:]

        lines = [

            "╔════════════════════════╗",
            "         📜 MY ORDERS",
            "╚════════════════════════╝",
            ""
        ]

        for order in reversed(
            user_orders
        ):

            lines.append(
                f"🧾 {order['order_id']}"
            )

            lines.append(
                f"🛍 {order['product_name']}"
            )

            lines.append(
                f"💵 ₹{order['price']}"
            )

            lines.append(
                f"📅 {order['date']}"
            )

            lines.append(
                f"📦 {order['status']}"
            )

            lines.append(
                f"🔗 /access {order['order_id']}"
            )

            lines.append(
                "────────────────────"
            )

        lines.append(
            "🔄 Use /access ORDER_ID for a fresh access link."
        )

        lines.append("")

        lines.append(
            USER_BRAND
        )

        bot.send_message(
            chat_id,
            "\n".join(lines),
            reply_markup=main_menu(
                user_id
            )
        )

    except Exception:

        logging.exception(
            "ORDERS ERROR"
        )

        bot.send_message(
            chat_id,
            "❌ Could not load orders."
        )


# =========================================================
# /ACCESS
# =========================================================

@bot.message_handler(
    commands=["access"]
)
def access_command(message):

    user_id = message.from_user.id

    parts = message.text.split()

    if len(parts) != 2:

        bot.send_message(
            message.chat.id,
            "❌ Usage:\n\n"
            "/access ORDER_ID"
        )

        return

    order_id = parts[1].strip()

    try:

        orders = get_orders()

        found_order = None

        for order in orders:

            if (
                order["order_id"] == order_id
                and
                order["user_id"] == user_id
            ):

                found_order = order

                break

        if not found_order:

            bot.send_message(
                message.chat.id,
                "❌ Order not found."
            )

            return

        product_id = found_order[
            "product_id"
        ]

        try:

            invite_link = create_product_invite(
                product_id
            )

        except Exception:

            logging.exception(
                "ACCESS LINK ERROR"
            )

            bot.send_message(
                message.chat.id,
                "❌ Could not generate access link.\n\n"
                "Please try again later."
            )

            return

        text = (
            "╔════════════════════════╗\n"
            "        🔐 ACCESS LINK\n"
            "╚════════════════════════╝\n\n"

            f"🧾 Order: {order_id}\n"
            f"🛍 Product: {found_order['product_name']}\n\n"

            "🟢 Fresh access link generated.\n\n"

            "⚠️ One-time use\n"
            "⏱️ Valid for 24 hours\n\n"

            "👇 Tap the button below to join.\n\n"

            f"{USER_BRAND}"
        )

        bot.send_message(
            message.chat.id,
            text,
            reply_markup=join_button(
                invite_link
            )
        )

    except Exception:

        logging.exception(
            "ACCESS ERROR"
        )

        bot.send_message(
            message.chat.id,
            "❌ Could not process access request."
        )


# =========================================================
# 💳 ADD FUNDS
# =========================================================

def start_add_funds(
    chat_id,
    user_id
):

    pending_funds[user_id] = {
        "stage": "amount"
    }

    text = (
        "╔════════════════════════╗\n"
        "         💳 ADD FUNDS\n"
        "╚════════════════════════╝\n\n"

        "💰 Enter the amount you want to add.\n\n"

        "Example:\n"
        "`500`\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"

        "🔐 Manual Payment\n"
        "Payment will be verified by admin.\n\n"

        f"{USER_BRAND}"
    )

    bot.send_message(
        chat_id,
        text,
        parse_mode="Markdown",
        reply_markup=back_menu()
    )


def send_payment_qr(
    chat_id,
    amount
):

    text = (
        "╔════════════════════════╗\n"
        "          💳 PAYMENT\n"
        "╚════════════════════════╝\n\n"

        f"💵 Amount: ₹{amount}\n\n"

        "📲 Scan the QR below and complete payment.\n\n"

        "After payment send:\n\n"

        "• 🔢 UTR / Transaction ID\n"
        "OR\n"
        "• 📸 Payment Screenshot\n\n"

        "⚠️ Balance will be added only after admin verification.\n\n"

        f"{USER_BRAND}"
    )

    try:

        with open(
            QR_FILE,
            "rb"
        ) as photo:

            bot.send_photo(
                chat_id,
                photo,
                caption=text,
                reply_markup=back_menu()
            )

    except FileNotFoundError:

        bot.send_message(
            chat_id,
            text
            + "\n\n"
            "❌ QR image is missing.\n"
            "Please contact admin."
        )


# =========================================================
# 👑 ADMIN /ADD
# =========================================================

@bot.message_handler(
    commands=["add"]
)
def add_balance_command(message):

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

        user_id = int(
            parts[1]
        )

        amount = int(
            parts[2]
        )

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
            "❌ Maximum amount is ₹10,00,000."
        )

        return

    try:

        with balance_lock:

            balances = get_balances()

            old_balance = balances.get(
                user_id,
                0
            )

            new_balance = (
                old_balance
                + amount
            )

            balances[user_id] = (
                new_balance
            )

            save_balances(
                balances
            )

        bot.send_message(
            message.chat.id,

            "╔════════════════════════╗\n"
            "       ✅ BALANCE ADDED\n"
            "╚════════════════════════╝\n\n"

            f"👤 User ID: {user_id}\n"
            f"💵 Added: ₹{amount}\n"
            f"💰 New Balance: ₹{new_balance}\n\n"

            f"{OWNER_BRAND}"
        )

        # Notify user
        try:

            bot.send_message(
                user_id,

                "╔════════════════════════╗\n"
                "       💰 BALANCE UPDATE\n"
                "╚════════════════════════╝\n\n"

                f"✅ Added: ₹{amount}\n"
                f"💰 Current Balance: ₹{new_balance}\n\n"

                "🛍 You can continue shopping now.\n\n"

                f"{USER_BRAND}",

                reply_markup=main_menu(
                    user_id
                )
            )

        except Exception:

            logging.info(
                "Could not notify user %s",
                user_id
            )

    except Exception:

        logging.exception(
            "ADD BALANCE ERROR"
        )

        bot.send_message(
            message.chat.id,
            "❌ Balance update failed."
        )


# =========================================================
# 📊 STATISTICS
# =========================================================

def show_statistics(
    chat_id
):

    try:

        balances = get_balances()

        orders = get_orders()

        total_users = len(
            balances
        )

        total_orders = len(
            orders
        )

        total_sales = sum(
            order["price"]
            for order in orders
        )

        total_balance = sum(
            balances.values()
        )

        product_sales = {
            1: 0,
            2: 0,
            3: 0
        }

        for order in orders:

            product_id = order[
                "product_id"
            ]

            if product_id in product_sales:

                product_sales[
                    product_id
                ] += 1

        text = (
            "╔════════════════════════╗\n"
            "        📊 STATISTICS\n"
            "╚════════════════════════╝\n\n"

            f"👥 Total Users: {total_users}\n"
            f"📦 Total Orders: {total_orders}\n"
            f"💰 Total Sales: ₹{total_sales}\n"
            f"💳 User Balances: ₹{total_balance}\n\n"

            "━━━━━━━━━━━━━━━━━━━━━━\n"

            f"① Product A: {product_sales[1]} sales\n"
            f"② Product B: {product_sales[2]} sales\n"
            f"③ Product C: {product_sales[3]} sales\n\n"

            f"{OWNER_BRAND}"
        )

        bot.send_message(
            chat_id,
            text,
            reply_markup=admin_menu()
        )

    except Exception:

        logging.exception(
            "STATISTICS ERROR"
        )

        bot.send_message(
            chat_id,
            "❌ Could not load statistics."
        )


# =========================================================
# 👑 ADMIN PANEL
# =========================================================

def show_admin_panel(
    chat_id
):

    text = (
        "╔════════════════════════╗\n"
        "         👑 ADMIN PANEL\n"
        "╚════════════════════════╝\n\n"

        "🔐 Owner Controls\n\n"

        "💳 Add Balance\n"
        "Manually credit user balance.\n\n"

        "📊 Statistics\n"
        "View users, orders & sales.\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"

        f"{OWNER_BRAND}"
    )

    bot.send_message(
        chat_id,
        text,
        reply_markup=admin_menu()
    )


# =========================================================
# 💳 FUNDS TEXT HANDLER
# =========================================================

def handle_funds_text(
    message
):

    user_id = message.from_user.id

    state = pending_funds.get(
        user_id
    )

    if not state:

        return False

    # =====================================================
    # AMOUNT
    # =====================================================

    if state["stage"] == "amount":

        raw_amount = message.text.strip()

        try:

            amount = int(
                raw_amount
            )

        except ValueError:

            bot.send_message(
                message.chat.id,
                "❌ Please enter a valid amount.\n\n"
                "Example: 500"
            )

            return True

        if amount <= 0:

            bot.send_message(
                message.chat.id,
                "❌ Amount must be greater than ₹0."
            )

            return True

        if amount > 1000000:

            bot.send_message(
                message.chat.id,
                "❌ Maximum amount is ₹10,00,000."
            )

            return True

        pending_funds[user_id] = {

            "stage": "proof",

            "amount": amount

        }

        send_payment_qr(
            message.chat.id,
            amount
        )

        return True

    # =====================================================
    # UTR / TRANSACTION ID
    # =====================================================

    if state["stage"] == "proof":

        amount = state[
            "amount"
        ]

        utr = message.text.strip()

        if len(utr) < 3:

            bot.send_message(
                message.chat.id,
                "❌ Please send a valid UTR / Transaction ID."
            )

            return True

        pending_funds.pop(
            user_id,
            None
        )

        try:

            bot.send_message(

                ADMIN_ID,

                "╔════════════════════════╗\n"
                "     💳 PAYMENT REQUEST\n"
                "╚════════════════════════╝\n\n"

                f"👤 User ID: {user_id}\n"
                f"💵 Amount: ₹{amount}\n"
                f"🔢 UTR: {utr}\n\n"

                "🔍 Verify the payment manually.\n\n"

                f"✅ Approve:\n"
                f"/add {user_id} {amount}\n\n"

                f"{OWNER_BRAND}"
            )

            bot.send_message(

                message.chat.id,

                "╔════════════════════════╗\n"
                "       ✅ SUBMITTED\n"
                "╚════════════════════════╝\n\n"

                f"💵 Amount: ₹{amount}\n"
                f"🔢 UTR: {utr}\n\n"

                "📨 Payment proof sent to admin.\n"
                "💰 Balance will be added after verification.\n\n"

                f"{USER_BRAND}",

                reply_markup=main_menu(
                    user_id
                )
            )

        except Exception:

            logging.exception(
                "UTR SEND ERROR"
            )

            bot.send_message(
                message.chat.id,
                "❌ Could not submit payment proof."
            )

        return True

    return False


# =========================================================
# 📸 PAYMENT SCREENSHOT
# =========================================================

@bot.message_handler(
    content_types=["photo"]
)
def payment_photo(
    message
):

    user_id = message.from_user.id

    state = pending_funds.get(
        user_id
    )

    if not state:
        return

    if state["stage"] != "proof":
        return

    amount = state[
        "amount"
    ]

    pending_funds.pop(
        user_id,
        None
    )

    try:

        caption = (

            "╔════════════════════════╗\n"
            "    💳 PAYMENT SCREENSHOT\n"
            "╚════════════════════════╝\n\n"

            f"👤 User ID: {user_id}\n"
            f"💵 Amount: ₹{amount}\n\n"

            "🔍 Verify payment manually.\n\n"

            f"✅ Approve:\n"
            f"/add {user_id} {amount}\n\n"

            f"{OWNER_BRAND}"
        )

        bot.send_photo(

            ADMIN_ID,

            message.photo[-1].file_id,

            caption=caption
        )

        bot.send_message(

            message.chat.id,

            "╔════════════════════════╗\n"
            "       ✅ SUBMITTED\n"
            "╚════════════════════════╝\n\n"

            f"💵 Amount: ₹{amount}\n\n"

            "📸 Screenshot sent to admin.\n"
            "💰 Balance will be added after verification.\n\n"

            f"{USER_BRAND}",

            reply_markup=main_menu(
                user_id
            )
        )

    except Exception:

        logging.exception(
            "PHOTO PROOF ERROR"
        )

        bot.send_message(
            message.chat.id,
            "❌ Could not submit screenshot."
        )


# =========================================================
# 👤 PROFILE
# =========================================================

def show_profile(
    chat_id,
    user_id,
    user
):

    try:

        balances = get_balances()

        balance = balances.get(
            user_id,
            0
        )

        orders = get_orders()

        total_orders = len([

            order

            for order in orders

            if order["user_id"] == user_id

        ])

        if user.username:

            username = (
                "@"
                + user.username
            )

        else:

            username = "Not set"

        first_name = (
            user.first_name
            or "User"
        )

        text = (
            "╔════════════════════════╗\n"
            "          👤 PROFILE\n"
            "╚════════════════════════╝\n\n"

            f"👋 Name: {first_name}\n"
            f"🔗 Username: {username}\n"
            f"🆔 User ID: `{user_id}`\n\n"

            "━━━━━━━━━━━━━━━━━━━━━━\n"

            f"💰 Balance: ₹{balance}\n"
            f"📦 Total Orders: {total_orders}\n\n"

            "━━━━━━━━━━━━━━━━━━━━━━\n"

            f"{USER_BRAND}"
        )

        bot.send_message(

            chat_id,

            text,

            parse_mode="Markdown",

            reply_markup=main_menu(
                user_id
            )
        )

    except Exception:

        logging.exception(
            "PROFILE ERROR"
        )

        bot.send_message(
            chat_id,
            "❌ Could not load profile."
        )


# =========================================================
# 💬 TEXT HANDLER
# =========================================================

@bot.message_handler(
    content_types=["text"]
)
def text_handler(
    message
):

    user_id = message.from_user.id

    text = message.text.strip()

    # =====================================================
    # FUNDS STATE FIRST
    # =====================================================

    if user_id in pending_funds:

        if handle_funds_text(
            message
        ):

            return

    # =====================================================
    # PRODUCTS
    # =====================================================

    if text == "🛍 Products":

        pending_funds.pop(
            user_id,
            None
        )

        show_products(
            message.chat.id,
            user_id
        )

        return

    # =====================================================
    # BALANCE
    # =====================================================

    if text == "💰 Balance":

        pending_funds.pop(
            user_id,
            None
        )

        balance_command(
            message
        )

        return

    # =====================================================
    # ADD FUNDS
    # =====================================================

    if text == "💳 Add Funds":

        start_add_funds(
            message.chat.id,
            user_id
        )

        return

    # =====================================================
    # MY ORDERS
    # =====================================================

    if text == "📜 My Orders":

        pending_funds.pop(
            user_id,
            None
        )

        show_my_orders(
            message.chat.id,
            user_id
        )

        return

    # =====================================================
    # PROFILE
    # =====================================================

    if text == "👤 Profile":

        pending_funds.pop(
            user_id,
            None
        )

        show_profile(
            message.chat.id,
            user_id,
            message.from_user
        )

        return

    # =====================================================
    # ADMIN PANEL
    # =====================================================

    if text == "👨‍💼 Admin Panel":

        if user_id != ADMIN_ID:

            bot.send_message(
                message.chat.id,
                "❌ Admin only."
            )

            return

        pending_funds.pop(
            user_id,
            None
        )

        show_admin_panel(
            message.chat.id
        )

        return

    # =====================================================
    # ADMIN ADD BALANCE
    # =====================================================

    if text == "💳 Add Balance":

        if user_id != ADMIN_ID:

            bot.send_message(
                message.chat.id,
                "❌ Admin only."
            )

            return

        bot.send_message(

            message.chat.id,

            "╔════════════════════════╗\n"
            "       💳 ADD BALANCE\n"
            "╚════════════════════════╝\n\n"

            "Use:\n\n"
            "/add USER_ID AMOUNT\n\n"

            "Example:\n"
            "/add 123456789 500\n\n"

            f"{OWNER_BRAND}",

            reply_markup=admin_menu()
        )

        return

    # =====================================================
    # STATISTICS
    # =====================================================

    if text == "📊 Statistics":

        if user_id != ADMIN_ID:

            bot.send_message(
                message.chat.id,
                "❌ Admin only."
            )

            return

        show_statistics(
            message.chat.id
        )

        return

    # =====================================================
    # MAIN MENU
    # =====================================================

    if text == "🏠 Main Menu":

        pending_funds.pop(
            user_id,
            None
        )

        send_welcome(
            message.chat.id,
            user_id
        )

        return

    # =====================================================
    # PRODUCT 1
    # =====================================================

    if text == "🛒 Buy Product 1":

        purchase_product(
            message,
            1
        )

        return

    # =====================================================
    # PRODUCT 2
    # =====================================================

    if text == "🛒 Buy Product 2":

        purchase_product(
            message,
            2
        )

        return

    # =====================================================
    # PRODUCT 3
    # =====================================================

    if text == "🛒 Buy Product 3":

        purchase_product(
            message,
            3
        )

        return

    # =====================================================
    # UNKNOWN MESSAGE
    # =====================================================

    bot.send_message(

        message.chat.id,

        "✨ Please use the menu below.",

        reply_markup=main_menu(
            user_id
        )
    )


# =========================================================
# 🌐 HOME
# =========================================================

@app.route(
    "/",
    methods=["GET"]
)
def home():

    return (
        "⚡ SpeedFistt Bot is running.",
        200
    )


# =========================================================
# 🌐 TELEGRAM WEBHOOK
# =========================================================

@app.route(
    "/webhook",
    methods=["POST"]
)
def webhook():

    try:

        data = request.get_data().decode(
            "utf-8"
        )

        update = telebot.types.Update.de_json(
            data
        )

        bot.process_new_updates(
            [update]
        )

        return "OK", 200

    except Exception:

        logging.exception(
            "WEBHOOK ERROR"
        )

        return "ERROR", 500


# =========================================================
# 🔗 SET WEBHOOK
# =========================================================

def setup_webhook():

    webhook_url = (
        f"{WEBHOOK_URL}/webhook"
    )

    try:

        bot.remove_webhook()

    except Exception:

        pass

    bot.set_webhook(

        url=webhook_url,

        allowed_updates=[
            "message",
            "channel_post"
        ]
    )

    logging.info(
        "WEBHOOK SET: %s",
        webhook_url
    )


# =========================================================
# START
# =========================================================

setup_webhook()


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
