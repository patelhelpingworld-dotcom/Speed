import os
import threading
import logging
from datetime import datetime, timedelta, timezone

import telebot
from telebot import types
from flask import Flask, request


# ==========================================
# CONFIG
# ==========================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")

ADMIN_ID = 1006157952

# Balance database channel
CHANNEL_ID = -1003892586354
BALANCE_MESSAGE_ID = 4

# Payment QR file
QR_FILE = "qr.jpg"


# ==========================================
# PRODUCT CONFIG
# ==========================================

PRODUCTS = {
    1: {
        "name": "Digital Product A",
        "price": 100,
        "group_id": -1004494287362
    },

    2: {
        "name": "Digital Product B",
        "price": 200,
        "group_id": -1003778035299
    },

    3: {
        "name": "Digital Product C",
        "price": 300,
        "group_id": -1004203063772
    }
}


# Invite settings
INVITE_MEMBER_LIMIT = 1
INVITE_EXPIRE_HOURS = 24


if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN environment variable is missing"
    )

if not WEBHOOK_URL:
    raise RuntimeError(
        "WEBHOOK_URL environment variable is missing"
    )


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

# User payment states
# Example:
# pending_funds[user_id] = {
#     "stage": "amount"
# }
#
# after amount:
# pending_funds[user_id] = {
#     "stage": "proof",
#     "amount": 500
# }
pending_funds = {}


# ==========================================
# MAIN MENU
# ==========================================

def main_menu(user_id):

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

    if user_id == ADMIN_ID:
        keyboard.row(
            "👨‍💼 Admin Panel"
        )

    return keyboard


# ==========================================
# ADMIN MENU
# ==========================================

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
                user_part.split(
                    ":",
                    1
                )[1].strip()
            )

            balance = int(
                float(
                    balance_part.split(
                        ":",
                        1
                    )[1].strip()
                )
            )

            balances[user_id] = balance

        except (
            ValueError,
            IndexError
        ):
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
                f"USER: {user_id} | "
                f"BALANCE: {balances[user_id]}"
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


# ==========================================
# START
# ==========================================

@bot.message_handler(
    commands=["start"]
)
def start_command(message):

    user_id = message.from_user.id

    try:

        with balance_lock:

            balances = get_balances()

            if user_id not in balances:

                balances[user_id] = 0

                save_balances(
                    balances
                )

        bot.send_message(
            message.chat.id,

            "👋 Welcome to SpeedFistt Store!\n\n"
            "Choose an option below:",

            reply_markup=main_menu(
                user_id
            )
        )

    except Exception:

        logging.exception(
            "START ERROR"
        )

        bot.send_message(
            message.chat.id,

            "❌ Store setup error.\n"
            "Please contact admin."
        )


# ==========================================
# BALANCE
# ==========================================

@bot.message_handler(
    func=lambda message:
    message.text == "💰 Balance"
)
def balance_button(message):

    user_id = message.from_user.id

    try:

        balances = get_balances()

        balance = balances.get(
            user_id,
            0
        )

        bot.send_message(
            message.chat.id,

            f"💰 Your balance: ₹{balance}",

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


@bot.message_handler(
    commands=["balance"]
)
def balance_command(message):

    balance_button(message)


# ==========================================
# PRODUCTS
# ==========================================

def show_products(
    chat_id,
    user_id
):

    keyboard = types.ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    keyboard.row(
        "🛒 Buy Product 1"
    )

    keyboard.row(
        "🛒 Buy Product 2"
    )

    keyboard.row(
        "🛒 Buy Product 3"
    )

    keyboard.row(
        "🏠 Main Menu"
    )

    bot.send_message(
        chat_id,

        "🛍 SPEEDFISTT STORE\n\n"

        "1️⃣ Digital Product A — ₹100\n\n"
        "2️⃣ Digital Product B — ₹200\n\n"
        "3️⃣ Digital Product C — ₹300\n\n"

        "👇 Select a product:",

        reply_markup=keyboard
    )


@bot.message_handler(
    func=lambda message:
    message.text == "🛍 Products"
)
def products_button(message):

    show_products(
        message.chat.id,
        message.from_user.id
    )


@bot.message_handler(
    commands=["products"]
)
def products_command(message):

    show_products(
        message.chat.id,
        message.from_user.id
    )


# ==========================================
# GENERATE LIMITED INVITE
# ==========================================

def generate_product_invite(
    product_id
):

    product = PRODUCTS[
        product_id
    ]

    group_id = product[
        "group_id"
    ]

    # 24 hours from now
    expiry = (
        datetime.now(timezone.utc)
        + timedelta(
            hours=INVITE_EXPIRE_HOURS
        )
    )

    invite = bot.create_chat_invite_link(
        chat_id=group_id,

        name=(
            f"Product {product_id}"
        ),

        expire_date=expiry,

        member_limit=INVITE_MEMBER_LIMIT,

        creates_join_request=False
    )

    return invite.invite_link


# ==========================================
# BUY
# ==========================================

def process_purchase(
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

    product_name = product[
        "name"
    ]

    price = product[
        "price"
    ]

    # --------------------------------------
    # FIRST generate invite
    # --------------------------------------

    try:

        invite_link = generate_product_invite(
            product_id
        )

    except Exception:

        logging.exception(
            "INVITE LINK ERROR"
        )

        bot.send_message(
            message.chat.id,

            "❌ Product delivery is "
            "currently unavailable.\n\n"
            "Please contact admin."
        )

        return

    # --------------------------------------
    # THEN deduct balance
    # --------------------------------------

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

                    f"🛍 Product: {product_name}\n"
                    f"💵 Price: ₹{price}\n"
                    f"💰 Your balance: "
                    f"₹{current_balance}\n\n"

                    "💳 Use Add Funds "
                    "to add balance."
                )

                return

            new_balance = (
                current_balance - price
            )

            balances[user_id] = new_balance

            save_balances(
                balances
            )

        # ----------------------------------
        # SEND DELIVERY
        # ----------------------------------

        bot.send_message(
            message.chat.id,

            "✅ PURCHASE SUCCESSFUL!\n\n"

            f"🛍 Product: {product_name}\n"
            f"💵 Price: ₹{price}\n"
            f"💰 Remaining Balance: "
            f"₹{new_balance}\n\n"

            "🔐 Your private access link:\n"
            f"{invite_link}\n\n"

            "⚠️ This link can be used "
            "only once.\n"
            "⏰ Link expires in 24 hours.",

            reply_markup=main_menu(
                user_id
            )
        )

    except Exception:

        logging.exception(
            "PURCHASE ERROR"
        )

        bot.send_message(
            message.chat.id,

            "❌ Purchase failed.\n"
            "Your balance was not changed."
        )


# ==========================================
# BUY COMMAND
# ==========================================

@bot.message_handler(
    commands=["buy"]
)
def buy_product(message):

    parts = message.text.split()

    if len(parts) != 2:

        bot.send_message(
            message.chat.id,

            "❌ Invalid product.\n\n"
            "Use Products menu."
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

    process_purchase(
        message,
        product_id
    )


# ==========================================
# PRODUCT BUTTONS
# ==========================================

@bot.message_handler(
    func=lambda message:
    message.text == "🛒 Buy Product 1"
)
def buy_product_1(message):

    process_purchase(
        message,
        1
    )


@bot.message_handler(
    func=lambda message:
    message.text == "🛒 Buy Product 2"
)
def buy_product_2(message):

    process_purchase(
        message,
        2
    )


@bot.message_handler(
    func=lambda message:
    message.text == "🛒 Buy Product 3"
)
def buy_product_3(message):

    process_purchase(
        message,
        3
    )


# ==========================================
# ADD FUNDS
# ==========================================

@bot.message_handler(
    func=lambda message:
    message.text == "💳 Add Funds"
)
def add_funds_start(message):

    user_id = message.from_user.id

    pending_funds[user_id] = {
        "stage": "amount"
    }

    keyboard = types.ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    keyboard.row(
        "🏠 Main Menu"
    )

    bot.send_message(
        message.chat.id,

        "💳 ADD FUNDS\n\n"

        "Kitna amount add karna hai?\n\n"

        "Example:\n"
        "100\n"
        "500\n"
        "1000",

        reply_markup=keyboard
    )


# ==========================================
# RECEIVE FUND AMOUNT
# ==========================================

@bot.message_handler(
    func=lambda message:
    (
        message.from_user.id in pending_funds
        and pending_funds[
            message.from_user.id
        ].get("stage") == "amount"
    )
)
def receive_funds_amount(message):

    user_id = message.from_user.id

    if message.text == "🏠 Main Menu":

        pending_funds.pop(
            user_id,
            None
        )

        bot.send_message(
            message.chat.id,

            "🏠 Main Menu",

            reply_markup=main_menu(
                user_id
            )
        )

        return

    text = (
        message.text
        .replace("₹", "")
        .replace(",", "")
        .strip()
    )

    try:

        amount = int(text)

    except ValueError:

        bot.send_message(
            message.chat.id,

            "❌ Invalid amount.\n\n"
            "Example: 500"
        )

        return

    if amount <= 0:

        bot.send_message(
            message.chat.id,

            "❌ Amount ₹0 se "
            "greater hona chahiye."
        )

        return

    if amount > 1000000:

        bot.send_message(
            message.chat.id,

            "❌ Maximum amount is "
            "₹10,00,000."
        )

        return

    pending_funds[user_id] = {
        "stage": "proof",
        "amount": amount
    }

    caption = (
        "💳 PAYMENT INSTRUCTIONS\n\n"

        f"💵 Amount: ₹{amount}\n\n"

        "1️⃣ QR scan karke payment karo.\n"
        f"2️⃣ Exactly ₹{amount} pay karo.\n"
        "3️⃣ Payment ke baad UTR "
        "ya screenshot bhejo.\n\n"

        "⚠️ Payment verify hone ke baad "
        "admin balance add karega."
    )

    try:

        with open(
            QR_FILE,
            "rb"
        ) as qr:

            bot.send_photo(
                message.chat.id,
                qr,
                caption=caption
            )

        bot.send_message(
            message.chat.id,

            "📸 Payment ke baad "
            "UTR number ya screenshot bhejo."
        )

    except FileNotFoundError:

        logging.exception(
            "QR FILE NOT FOUND"
        )

        pending_funds.pop(
            user_id,
            None
        )

        bot.send_message(
            message.chat.id,

            "❌ Payment QR unavailable.\n"
            "Please contact admin."
        )

    except Exception:

        logging.exception(
            "QR SEND ERROR"
        )

        bot.send_message(
            message.chat.id,

            "❌ QR send nahi ho paya."
        )


# ==========================================
# PAYMENT SCREENSHOT
# ==========================================

@bot.message_handler(
    content_types=["photo"]
)
def payment_screenshot(message):

    user_id = message.from_user.id

    payment = pending_funds.get(
        user_id
    )

    if not payment:
        return

    if payment.get("stage") != "proof":
        return

    amount = payment[
        "amount"
    ]

    try:

        bot.forward_message(
            ADMIN_ID,
            message.chat.id,
            message.message_id
        )

        bot.send_message(
            ADMIN_ID,

            "💳 NEW PAYMENT REQUEST\n\n"

            f"👤 User ID: {user_id}\n"
            f"💵 Amount: ₹{amount}\n\n"

            f"Approve after verification:\n"
            f"/add {user_id} {amount}"
        )

        bot.send_message(
            message.chat.id,

            "✅ Payment screenshot "
            "admin ko bhej diya gaya hai.\n\n"

            "⏳ Verification ke baad "
            "balance add hoga.",

            reply_markup=main_menu(
                user_id
            )
        )

        pending_funds.pop(
            user_id,
            None
        )

    except Exception:

        logging.exception(
            "PAYMENT SCREENSHOT ERROR"
        )

        bot.send_message(
            message.chat.id,

            "❌ Payment proof send "
            "nahi ho paya."
        )


# ==========================================
# PAYMENT UTR
# ==========================================

@bot.message_handler(
    func=lambda message:
    (
        message.from_user.id in pending_funds
        and pending_funds[
            message.from_user.id
        ].get("stage") == "proof"
        and message.content_type == "text"
    )
)
def payment_utr(message):

    user_id = message.from_user.id

    if message.text == "🏠 Main Menu":

        pending_funds.pop(
            user_id,
            None
        )

        bot.send_message(
            message.chat.id,

            "🏠 Main Menu",

            reply_markup=main_menu(
                user_id
            )
        )

        return

    payment = pending_funds.get(
        user_id
    )

    if not payment:
        return

    amount = payment[
        "amount"
    ]

    utr = message.text.strip()

    if len(utr) < 6:

        bot.send_message(
            message.chat.id,

            "❌ UTR valid nahi lag raha.\n\n"
            "Correct UTR bhejo."
        )

        return

    try:

        bot.send_message(
            ADMIN_ID,

            "💳 NEW PAYMENT REQUEST\n\n"

            f"👤 User ID: {user_id}\n"
            f"💵 Amount: ₹{amount}\n"
            f"🔢 UTR: {utr}\n\n"

            "Payment verify karke:\n"
            f"/add {user_id} {amount}"
        )

        bot.send_message(
            message.chat.id,

            "✅ UTR admin ko bhej diya gaya hai.\n\n"
            "⏳ Payment verification ke baad "
            "balance add hoga.",

            reply_markup=main_menu(
                user_id
            )
        )

        pending_funds.pop(
            user_id,
            None
        )

    except Exception:

        logging.exception(
            "PAYMENT UTR ERROR"
        )

        bot.send_message(
            message.chat.id,

            "❌ UTR send nahi ho paya."
        )


# ==========================================
# ADMIN PANEL
# ==========================================

@bot.message_handler(
    func=lambda message:
    message.text == "👨‍💼 Admin Panel"
)
def admin_panel(message):

    if message.from_user.id != ADMIN_ID:

        bot.send_message(
            message.chat.id,
            "❌ Admin only."
        )

        return

    bot.send_message(
        message.chat.id,

        "👨‍💼 ADMIN PANEL\n\n"
        "💳 Add Balance\n"
        "📊 Statistics",

        reply_markup=admin_menu()
    )


# ==========================================
# ADMIN ADD BALANCE BUTTON
# ==========================================

@bot.message_handler(
    func=lambda message:
    message.text == "💳 Add Balance"
)
def admin_add_balance_button(message):

    if message.from_user.id != ADMIN_ID:

        bot.send_message(
            message.chat.id,
            "❌ Admin only."
        )

        return

    bot.send_message(
        message.chat.id,

        "💳 ADD BALANCE\n\n"

        "Use:\n"
        "/add USER_ID AMOUNT\n\n"

        "Example:\n"
        "/add 123456789 500"
    )


# ==========================================
# ADMIN ADD BALANCE
# ==========================================

@bot.message_handler(
    commands=["add"]
)
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

        user_id = int(
            parts[1]
        )

        amount = int(
            parts[2]
        )

    except ValueError:

        bot.send_message(
            message.chat.id,

            "❌ User ID and amount "
            "must be numbers."
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

            "❌ Amount must be "
            "greater than ₹0."
        )

        return

    if amount > 1000000:

        bot.send_message(
            message.chat.id,

            "❌ Maximum allowed "
            "amount is ₹10,00,000."
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
                old_balance + amount
            )

            balances[user_id] = (
                new_balance
            )

            save_balances(
                balances
            )

        bot.send_message(
            message.chat.id,

            "✅ BALANCE ADDED\n\n"

            f"👤 User ID: {user_id}\n"
            f"💵 Added: ₹{amount}\n"
            f"💰 New Balance: ₹{new_balance}"
        )

        try:

            bot.send_message(
                user_id,

                "💰 Balance Added!\n\n"

                f"Added: ₹{amount}\n"
                f"Current Balance: "
                f"₹{new_balance}"
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


# ==========================================
# STATISTICS
# ==========================================

@bot.message_handler(
    func=lambda message:
    message.text == "📊 Statistics"
)
def statistics(message):

    if message.from_user.id != ADMIN_ID:

        bot.send_message(
            message.chat.id,
            "❌ Admin only."
        )

        return

    try:

        balances = get_balances()

        total_users = len(
            balances
        )

        total_balance = sum(
            balances.values()
        )

        bot.send_message(
            message.chat.id,

            "📊 STORE STATISTICS\n\n"

            f"👥 Users: {total_users}\n"
            f"💰 Total Balance: "
            f"₹{total_balance}"
        )

    except Exception:

        logging.exception(
            "STATISTICS ERROR"
        )

        bot.send_message(
            message.chat.id,

            "❌ Statistics unavailable."
        )


# ==========================================
# MAIN MENU
# ==========================================

@bot.message_handler(
    func=lambda message:
    message.text == "🏠 Main Menu"
)
def main_menu_button(message):

    user_id = message.from_user.id

    pending_funds.pop(
        user_id,
        None
    )

    bot.send_message(
        message.chat.id,

        "🏠 SPEEDFISTT STORE\n\n"
        "Choose an option:",

        reply_markup=main_menu(
            user_id
        )
    )


# ==========================================
# PROFILE
# ==========================================

@bot.message_handler(
    func=lambda message:
    message.text == "👤 Profile"
)
def profile(message):

    user = message.from_user

    try:

        balances = get_balances()

        balance = balances.get(
            user.id,
            0
        )

        bot.send_message(
            message.chat.id,

            "👤 PROFILE\n\n"

            f"🆔 User ID: {user.id}\n"
            f"👤 Name: {user.first_name}\n"
            f"💰 Balance: ₹{balance}",

            reply_markup=main_menu(
                user.id
            )
        )

    except Exception:

        bot.send_message(
            message.chat.id,

            "❌ Profile unavailable."
        )


# ==========================================
# MY ORDERS
# ==========================================

@bot.message_handler(
    func=lambda message:
    message.text == "📜 My Orders"
)
def my_orders(message):

    bot.send_message(
        message.chat.id,

        "📜 MY ORDERS\n\n"
        "Order history feature "
        "will be added soon.",

        reply_markup=main_menu(
            message.from_user.id
        )
    )


# ==========================================
# WEBHOOK
# ==========================================

@app.route(
    "/",
    methods=["GET"]
)
def home():

    return (
        "SpeedFistt Store Bot is running.",
        200
    )


@app.route(
    "/webhook",
    methods=["POST"]
)
def webhook():

    try:

        data = request.get_data().decode(
            "utf-8"
        )

        logging.info(
            "TELEGRAM UPDATE RECEIVED: %s",
            data
        )

        update = (
            telebot.types.Update.de_json(
                data
            )
        )

        bot.process_new_updates(
            [update]
        )

        logging.info(
            "UPDATE PROCESSED SUCCESSFULLY"
        )

        return "OK", 200

    except Exception:

        logging.exception(
            "WEBHOOK ERROR"
        )

        return "ERROR", 500


# ==========================================
# SET WEBHOOK
# ==========================================

def setup_webhook():

    webhook_url = (
        f"{WEBHOOK_URL}/webhook"
    )

    bot.remove_webhook()

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


setup_webhook()


# ==========================================
# RUN
# ==========================================

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
