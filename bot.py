import os
import re
import time
import logging
import queue
import threading
from functools import wraps
from datetime import datetime, timedelta
from pathlib import Path

import telebot
from telebot import types
from flask import Flask, request

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://speed-b8rg.onrender.com")

ADMIN_ID = 1006157952

# Balance database channel
BALANCE_DB_CHAT_ID = -1003892586354
BALANCE_DB_MESSAGE_ID = 4

# Orders + coupons database channel
ORDERS_DB_CHAT_ID = -1003892586354
ORDERS_DB_MESSAGE_ID = 8

OWNER_USERNAME = "@SpeedFistt"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable missing")

bot = telebot.TeleBot(
    BOT_TOKEN,
    threaded=False
)

app = Flask(__name__)

# Serialize database read-modify-write operations. RLock allows
# mutation functions to safely call load/save helpers internally.
DB_LOCK = threading.RLock()

def db_locked(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        with DB_LOCK:
            return func(*args, **kwargs)
    return wrapper

# =========================================================
# WEBHOOK UPDATE PROCESSING
# =========================================================
# Webhook request ko turant 200 OK milta hai, aur Telegram update
# background thread me process hota hai. Isse slow handler webhook
# request ko block nahi karta, aur custom queue/worker deadlock risk
# avoid hota hai.
# =========================================================

UPDATE_THREAD_SEMAPHORE = threading.BoundedSemaphore(20)

def process_update_background(update):
    acquired = UPDATE_THREAD_SEMAPHORE.acquire(timeout=5)
    if not acquired:
        logging.error("UPDATE PROCESSING BUSY")
        return
    try:
        bot.process_new_updates([update])
    except Exception:
        logging.exception("UPDATE PROCESSING ERROR")
    finally:
        UPDATE_THREAD_SEMAPHORE.release()


# =========================================================
# MANDATORY CHANNELS
# =========================================================

MANDATORY_CHANNELS = [
    {
        "id": -1001867059625,
        "link": "https://t.me/+U3dzaMEqyJY3MzJl",
        "name": "Channel 1"
    },
    {
        "id": -1002389473373,
        "link": "https://t.me/+9LkvQ9ATLSdkYTQ1",
        "name": "Channel 2"
    },
    {
        "id": -1002688365315,
        "link": "https://t.me/+63MXGMQmP-M3MTg1",
        "name": "Channel 3"
    }
]

# =========================================================
# PRODUCTS
# =========================================================

PRODUCTS = {
    1: {
        "name": "OBB & FILES",
        "price": 499,
        "group_id": -1004494287362
    },
    2: {
        "name": "Month (ESP+AIMBOT)",
        "price": 599,
        "group_id": -1003778035299
    },
    3: {
        "name": "Season (ESP+AIMBOT)",
        "price": 1199,
        "group_id": -1004203063772
    }
}

# =========================================================
# RUNTIME STATE
# =========================================================

user_states = {}
pending_funding = {}
recent_purchases = {}

# =========================================================
# HELPERS
# =========================================================

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_admin(user_id):
    return user_id == ADMIN_ID


def safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


# =========================================================
# BALANCE DATABASE
# =========================================================
#
# Supported old format:
# USER: 123 | BALANCE: 100
#
# New format:
# USER: 123 | BALANCE: 100 | REF: 456 | REWARDED: 0 | REF_BAL: 20
# =========================================================

def parse_balance_db(text):
    users = {}

    if not text:
        return users

    for line in text.splitlines():
        line = line.strip()

        if not line.startswith("USER:"):
            continue

        parts = [x.strip() for x in line.split("|")]

        data = {}

        for part in parts:
            if ":" not in part:
                continue

            key, value = part.split(":", 1)
            data[key.strip()] = value.strip()

        user_id = safe_int(data.get("USER"))

        if not user_id:
            continue

        users[user_id] = {
            "balance": safe_int(data.get("BALANCE")),
            "ref": safe_int(data.get("REF")),
            "rewarded": safe_int(data.get("REWARDED")),
            "ref_balance": safe_int(data.get("REF_BAL"))
        }

    return users


def load_balance_db():
    try:
        forwarded = bot.forward_message(
            ADMIN_ID,
            BALANCE_DB_CHAT_ID,
            BALANCE_DB_MESSAGE_ID
        )

        text = forwarded.text or ""

        try:
            bot.delete_message(
                ADMIN_ID,
                forwarded.message_id
            )
        except Exception:
            pass

        return parse_balance_db(text)

    except Exception:
        logging.exception("BALANCE DB LOAD ERROR")
        return None


def save_balance_db(users):
    lines = []

    for user_id, data in users.items():
        lines.append(
            f"USER: {user_id} | "
            f"BALANCE: {data.get('balance', 0)} | "
            f"REF: {data.get('ref', 0)} | "
            f"REWARDED: {data.get('rewarded', 0)} | "
            f"REF_BAL: {data.get('ref_balance', 0)}"
        )

    new_text = "\n".join(lines)

    try:
        bot.edit_message_text(
            new_text if new_text else "DATABASE EMPTY",
            BALANCE_DB_CHAT_ID,
            BALANCE_DB_MESSAGE_ID
        )
        return True

    except Exception:
        logging.exception("BALANCE DB SAVE ERROR")
        return False


def get_or_create_user(users, user_id):
    if user_id not in users:
        users[user_id] = {
            "balance": 0,
            "ref": 0,
            "rewarded": 0,
            "ref_balance": 0
        }

    return users[user_id]


# =========================================================
# ORDERS DATABASE
# =========================================================

def load_orders_db():
    try:
        forwarded = bot.forward_message(
            ADMIN_ID,
            ORDERS_DB_CHAT_ID,
            ORDERS_DB_MESSAGE_ID
        )

        text = forwarded.text or ""

        try:
            bot.delete_message(
                ADMIN_ID,
                forwarded.message_id
            )
        except Exception:
            pass

        return text

    except Exception:
        logging.exception("ORDERS DB LOAD ERROR")
        return None


def save_orders_db(text):
    if text is None:
        return False

    try:
        bot.edit_message_text(
            text if text else "DATABASE EMPTY",
            ORDERS_DB_CHAT_ID,
            ORDERS_DB_MESSAGE_ID
        )
        return True

    except Exception:
        logging.exception("ORDERS DB SAVE ERROR")
        return False


@db_locked
def append_order(order_line):
    text = load_orders_db()

    if text is None:
        return False

    lines = [
        x.strip()
        for x in text.splitlines()
        if x.strip()
    ]

    # Keep coupon lines
    coupon_lines = [
        x for x in lines
        if x.startswith("COUPON|")
    ]

    order_lines = [
        x for x in lines
        if x.startswith("ORDER|")
    ]

    order_lines.append(order_line)

    # Latest 40 orders
    order_lines = order_lines[-40:]

    final_lines = order_lines + coupon_lines

    return save_orders_db("\n".join(final_lines))


# =========================================================
# MANDATORY JOIN CHECK
# =========================================================

def is_member_of_channel(user_id, channel_id):
    try:
        member = bot.get_chat_member(
            chat_id=channel_id,
            user_id=user_id
        )

        logging.info(
            "JOIN CHECK | channel=%s user=%s status=%s",
            channel_id,
            user_id,
            member.status
        )

        return member.status in (
            "member",
            "administrator",
            "creator"
        )

    except Exception as e:
        logging.exception(
            "JOIN CHECK FAILED | channel=%s user=%s",
            channel_id,
            user_id
        )
        return False


def check_all_channels(user_id):
    missing = []

    for channel in MANDATORY_CHANNELS:
        if not is_member_of_channel(
            user_id,
            channel["id"]
        ):
            missing.append(channel)

    return missing


def send_join_required(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=1)

    for channel in MANDATORY_CHANNELS:
        markup.add(
            types.InlineKeyboardButton(
                f"📢 JOIN {channel['name']}",
                url=channel["link"]
            )
        )

    markup.add(
        types.InlineKeyboardButton(
            "✅ I'VE JOINED",
            callback_data="check_join"
        )
    )

    bot.send_message(
        chat_id,
        "🔐 <b>Join Required</b>\n\n"
        "Bot use karne se pehle neeche diye gaye "
        "teeno channels join karo.\n\n"
        "Join karne ke baad "
        "<b>✅ I'VE JOINED</b> press karo.",
        parse_mode="HTML",
        reply_markup=markup
    )


def require_join(message):
    missing = check_all_channels(message.from_user.id)

    if missing:
        send_join_required(message.chat.id)
        return False

    return True


# =========================================================
# MAIN MENU
# =========================================================

def main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    markup.row(
        "🛍 Hacks",
        "💰 Balance"
    )

    markup.row(
        "💳 Add Funds",
        "📜 My Orders"
    )

    markup.row(
        "👤 Profile",
        "👥 Referral"
    )

    if is_admin(user_id):
        markup.row("👨‍💼 Admin Panel")

    return markup


def admin_menu():
    markup = types.ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    markup.row(
        "💳 Add Balance",
        "📊 Statistics"
    )

    markup.row("🏠 Main Menu")

    return markup


# =========================================================
# PRODUCTS MENU
# =========================================================

def products_menu():
    markup = types.ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    markup.row(
        "🛒 Buy Product 1",
        "🛒 Buy Product 2"
    )

    markup.row(
        "🛒 Buy Product 3"
    )

    markup.row(
        "🎟 Apply Coupon",
        "🏠 Main Menu"
    )

    return markup


def send_products(chat_id):
    text = (
        "🛍 <b>Products</b>\n\n"
        "1️⃣ OBB & FILES — ₹499/-\n"
        "2️⃣ Month (ESP+AIMBOT) — ₹999/-\n"
        "3️⃣ Season (ESP+AIMBOT) — ₹1499/-\n\n"
        "👇 Product select karke purchase karo."
    )

    bot.send_message(
        chat_id,
        text,
        parse_mode="HTML",
        reply_markup=products_menu()
    )


# =========================================================
# COUPON HELPERS
# =========================================================

def parse_coupons(text):
    coupons = {}

    if not text:
        return coupons

    for line in text.splitlines():
        if not line.startswith("COUPON|"):
            continue

        parts = line.split("|")

        if len(parts) < 6:
            continue

        code = parts[1].upper()

        coupons[code] = {
            "pct": safe_int(parts[2]),
            "max": safe_int(parts[3]),
            "used": safe_int(parts[4]),
            "active": safe_int(parts[5])
        }

    return coupons


def get_coupon(code):
    text = load_orders_db()

    if text is None:
        return None

    coupons = parse_coupons(text)

    return coupons.get(code.upper())


@db_locked
def update_coupon_usage(code):
    text = load_orders_db()

    if text is None:
        return False

    lines = []

    updated = False

    for line in text.splitlines():
        if not line.startswith("COUPON|"):
            lines.append(line)
            continue

        parts = line.split("|")

        if len(parts) < 6:
            lines.append(line)
            continue

        if parts[1].upper() == code.upper():
            used = safe_int(parts[4]) + 1

            parts[4] = str(used)

            line = "|".join(parts)
            updated = True

        lines.append(line)

    if not updated:
        return False

    return save_orders_db("\n".join(
        x for x in lines if x.strip()
    ))


# =========================================================
# REFERRAL DEEP LINK
# =========================================================

def get_bot_username():
    try:
        me = bot.get_me()
        return me.username
    except Exception:
        return None


def referral_link(user_id):
    username = get_bot_username()

    if not username:
        return None

    return f"https://t.me/{username}?start=ref_{user_id}"


# =========================================================
# START
# =========================================================

@bot.message_handler(commands=["start"])
def start_command(message):
    user_id = message.from_user.id

    args = message.text.split(maxsplit=1)

    referrer_id = 0

    if len(args) > 1:
        arg = args[1].strip()

        if arg.startswith("ref_"):
            referrer_id = safe_int(
                arg.replace("ref_", "", 1)
            )

    users = load_balance_db()

    if users is None:
        bot.send_message(
            message.chat.id,
            "⚠️ Database temporarily unavailable. "
            "Please try again later."
        )
        return

    is_new_user = user_id not in users
    user = get_or_create_user(users, user_id)
    changed = is_new_user

    # Save referral attribution only once
    if (
        referrer_id
        and referrer_id != user_id
        and user["ref"] == 0
        and referrer_id in users
    ):
        user["ref"] = referrer_id
        changed = True

    if changed and not save_balance_db(users):
        bot.send_message(
            message.chat.id,
            "⚠️ User data save nahi ho saka. Please /start dobara try karo."
        )
        return

    missing = check_all_channels(user_id)

    if missing:
        send_join_required(message.chat.id)
        return

    bot.send_message(
    message.chat.id,
    f"Welcome! 👋 {username}\n\n👑 Owner: @SpeedFistt\n",
    reply_markup=main_menu(user_id)
)


# =========================================================
# JOIN CALLBACK
# =========================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "check_join"
)
def check_join_callback(call):
    user_id = call.from_user.id

    # Check all mandatory channels
    missing = check_all_channels(user_id)

    if missing:
        bot.answer_callback_query(
            call.id,
            "❌ Abhi saare channels join nahi hue.",
            show_alert=True
        )
        return

    # Load balance database
    users = load_balance_db()

    if users is None:
        bot.answer_callback_query(
            call.id,
            "⚠️ Database unavailable.",
            show_alert=True
        )
        return

    # Make sure user exists
    user = get_or_create_user(
        users,
        user_id
    )

    # Give referral reward only once
    reward_given = reward_referrer_after_verification(
        users,
        user_id
    )

    # Save database only if reward was given
    if reward_given:
        if not save_balance_db(users):
            bot.answer_callback_query(
                call.id,
                "⚠️ Reward save nahi ho saka. Please try again.",
                show_alert=True
            )
            return

    bot.answer_callback_query(
        call.id,
        "✅ Verification successful!"
    )

    try:
        bot.delete_message(
            call.message.chat.id,
            call.message.message_id
        )
    except Exception:
        pass

    reward_text = ""

    if reward_given:
        reward_text = (
            "\n\n🎉 <b>Referral Reward!</b>\n"
            "Aapke referrer ko ₹20 referral balance mila."
        )

    bot.send_message(
        call.message.chat.id,
        "✅ <b>Verified!</b>\n\n"
        "Ab aap bot use kar sakte ho."
        + reward_text,
        parse_mode="HTML",
        reply_markup=main_menu(user_id)
    )


# =========================================================
# REFERRAL REWARD AFTER CHANNEL VERIFICATION
# =========================================================

@db_locked
def reward_referrer_after_verification(users, buyer_id):
    buyer = users.get(buyer_id)

    if not buyer:
        return False

    # Already rewarded
    if buyer.get("rewarded", 0) == 1:
        return False

    referrer_id = buyer.get("ref", 0)

    # No referrer
    if not referrer_id:
        return False

    # Referrer must exist
    referrer = users.get(referrer_id)

    if not referrer:
        return False

    # Give ₹20 referral reward
    referrer["ref_balance"] = (
        referrer.get("ref_balance", 0) + 20
    )

    # Mark this referral as rewarded
    buyer["rewarded"] = 1

    return True
    
# =========================================================
# BALANCE
# =========================================================

def show_balance(chat_id, user_id):
    users = load_balance_db()

    if users is None:
        bot.send_message(
            chat_id,
            "⚠️ Database unavailable."
        )
        return

    user = get_or_create_user(users, user_id)

    if user_id not in users:
        save_balance_db(users)

    bot.send_message(
        chat_id,
        f"💰 <b>Main Balance:</b> ₹{user['balance']}\n"
        f"🎁 <b>Referral Balance:</b> ₹{user['ref_balance']}\n\n"
        f"ℹ️ Referral balance sirf purchases mein use ho sakta hai.",
        parse_mode="HTML"
    )


# =========================================================
# PROFILE
# =========================================================

def show_profile(message):
    user = message.from_user

    username = (
        f"@{user.username}"
        if user.username
        else "Not set"
    )

    bot.send_message(
        message.chat.id,
        "👤 <b>Profile</b>\n\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"👤 Username: {username}",
        parse_mode="HTML"
    )


# =========================================================
# REFERRAL PAGE
# =========================================================

def show_referral(message):
    user_id = message.from_user.id

    link = referral_link(user_id)

    if not link:
        bot.send_message(
            message.chat.id,
            "⚠️ Referral link generate nahi ho saka."
        )
        return

    users = load_balance_db()

    if users is None:
        bot.send_message(
            message.chat.id,
            "⚠️ Database unavailable."
        )
        return

    user = get_or_create_user(users, user_id)

    referral_text = (
        "👥 <b>REFER & EARN</b>\n\n"
        "🎁 Har successful referral par <b>₹20</b> referral balance\n"
        "🔗 Apna unique referral link share karo\n"
        "💰 Referral balance se eligible purchases me save karo\n\n"
        f"🔗 <b>Your Referral Link:</b>\n"
        f"<code>{link}</code>\n\n"
        f"🎁 <b>Current Referral Balance:</b> ₹{user['ref_balance']}\n\n"
        "⚠️ Referral balance withdraw/transfer/cash-out nahi kiya ja sakta."
    )

    banner_path = "referral_banner.png"

    try:
        if Path(banner_path).exists():
            with open(banner_path, "rb") as photo:
                bot.send_photo(
                    message.chat.id,
                    photo,
                    caption=referral_text,
                    parse_mode="HTML"
                )
        else:
            bot.send_message(
                message.chat.id,
                referral_text,
                parse_mode="HTML"
            )
    except Exception:
        logging.exception("REFERRAL BANNER ERROR")
        bot.send_message(
            message.chat.id,
            referral_text,
            parse_mode="HTML"
        )

# =========================================================
# PURCHASE / DELIVERY SYSTEM
# =========================================================

def calculate_coupon_discount(price, coupon):
    if not coupon:
        return 0

    pct = coupon.get("pct", 0)

    if pct < 0:
        pct = 0

    if pct > 100:
        pct = 100

    return (price * pct) // 100


def create_product_invite(product_id):
    product = PRODUCTS.get(product_id)

    if not product:
        return None

    group_id = product["group_id"]

    # Fresh invite:
    # - 1 user only
    # - valid for 24 hours
    expire_timestamp = int(
        (datetime.now() + timedelta(hours=24)).timestamp()
    )

    try:
        invite = bot.create_chat_invite_link(
            chat_id=group_id,
            name=f"Product {product_id}",
            expire_date=expire_timestamp,
            member_limit=1
        )

        return invite.invite_link

    except Exception:
        logging.exception(
            "INVITE CREATE ERROR product=%s",
            product_id
        )
        return None


def generate_order_id(user_id, product_id):
    timestamp = int(time.time())

    return f"ORD{timestamp}{user_id % 10000}{product_id}"


def get_user_orders(user_id):
    text = load_orders_db()

    if text is None:
        return None

    orders = []

    for line in text.splitlines():
        if not line.startswith("ORDER|"):
            continue

        parts = line.split("|")

        if len(parts) < 9:
            continue

        # ORDER|orderid|userid|productid|productname|price|date|status|coupon
        order_user_id = safe_int(parts[2])

        if order_user_id != user_id:
            continue

        orders.append({
            "order_id": parts[1],
            "user_id": order_user_id,
            "product_id": safe_int(parts[3]),
            "product_name": parts[4],
            "price": safe_int(parts[5]),
            "date": parts[6],
            "status": parts[7],
            "coupon": parts[8]
        })

    return orders


def show_orders(message):
    user_id = message.from_user.id

    orders = get_user_orders(user_id)

    if orders is None:
        bot.send_message(
            message.chat.id,
            "⚠️ Orders database unavailable."
        )
        return

    if not orders:
        bot.send_message(
            message.chat.id,
            "📜 <b>My Orders</b>\n\n"
            "Abhi koi order nahi hai.",
            parse_mode="HTML"
        )
        return

    orders = orders[-10:]
    orders.reverse()

    lines = [
        "📜 <b>My Orders</b>",
        ""
    ]

    for order in orders:
        coupon_text = ""

        if order["coupon"] and order["coupon"] != "-":
            coupon_text = f"\n🎟 Coupon: {order['coupon']}"

        lines.append(
            f"🧾 <b>{order['order_id']}</b>\n"
            f"📦 {order['product_name']}\n"
            f"💰 ₹{order['price']}\n"
            f"📅 {order['date']}\n"
            f"📌 {order['status']}"
            f"{coupon_text}\n"
            f"🔑 <code>/access {order['order_id']}</code>\n"
        )

    bot.send_message(
        message.chat.id,
        "\n".join(lines),
        parse_mode="HTML"
    )

# =========================================================
# PURCHASE CONFIRMATION
# =========================================================

purchase_guard = {}
purchase_guard_lock = threading.Lock()
PURCHASE_GUARD_SECONDS = 2


@db_locked
def send_purchase_confirmation(
    message,
    product_id,
    coupon_code=None
):
    user_id = message.from_user.id

    # Prevent accidental double-taps from creating two purchases.
    purchase_key = (
        user_id,
        product_id,
        (coupon_code or "-").upper()
    )

    now_ts = time.time()

    with purchase_guard_lock:
        previous_ts = purchase_guard.get(purchase_key, 0)

        if now_ts - previous_ts < PURCHASE_GUARD_SECONDS:
            bot.send_message(
                message.chat.id,
                "⚠️ Ye purchase request abhi process ho rahi hai. "
                "Duplicate order nahi banaya gaya."
            )
            return

        purchase_guard[purchase_key] = now_ts

        # Keep the small in-memory guard clean.
        cutoff = now_ts - 60
        for key, ts in list(purchase_guard.items()):
            if ts < cutoff:
                purchase_guard.pop(key, None)

    # -----------------------------------------------------
    # Mandatory channels check AGAIN
    # -----------------------------------------------------

    if not require_join(message):
        return

    product = PRODUCTS.get(product_id)

    if not product:
        bot.send_message(
            message.chat.id,
            "❌ Invalid product."
        )
        return

    
    # -----------------------------------------------------
    # Load balance database
    # -----------------------------------------------------

    users = load_balance_db()

    if users is None:
        bot.send_message(
            message.chat.id,
            "⚠️ Balance database unavailable.\n"
            "Purchase cancelled."
        )
        return

    user = get_or_create_user(
        users,
        user_id
    )

    # -----------------------------------------------------
    # Coupon
    # -----------------------------------------------------

    coupon = None
    coupon_code_clean = "-"

    if coupon_code:
        coupon_code_clean = coupon_code.upper()

        coupon = get_coupon(
            coupon_code_clean
        )

        if not coupon:
            bot.send_message(
                message.chat.id,
                "❌ Coupon invalid ya disabled hai."
            )
            return

        if coupon.get("active", 0) != 1:
            bot.send_message(
                message.chat.id,
                "❌ Coupon inactive hai."
            )
            return

        max_uses = coupon.get("max", 0)
        used = coupon.get("used", 0)

        if max_uses > 0 and used >= max_uses:
            bot.send_message(
                message.chat.id,
                "❌ Coupon usage limit complete ho gayi."
            )
            return

    # -----------------------------------------------------
    # Calculate price
    # -----------------------------------------------------

    original_price = product["price"]

    coupon_discount = calculate_coupon_discount(
        original_price,
        coupon
    )

    price_after_coupon = (
        original_price - coupon_discount
    )

    # -----------------------------------------------------
    # Referral balance max 50%
    # -----------------------------------------------------

    referral_balance = user.get(
        "ref_balance",
        0
    )

    max_referral_allowed = (
        price_after_coupon // 2
    )

    referral_used = min(
        referral_balance,
        max_referral_allowed
    )

    main_balance_needed = (
        price_after_coupon - referral_used
    )

    main_balance = user.get(
        "balance",
        0
    )

    # -----------------------------------------------------
    # Check balance
    # -----------------------------------------------------

    if main_balance < main_balance_needed:
        bot.send_message(
            message.chat.id,
            "❌ <b>Insufficient Balance</b>\n\n"
            f"📦 Product: {product['name']}\n"
            f"💰 Product Price: ₹{original_price}\n"
            f"🎟 Coupon Discount: ₹{coupon_discount}\n"
            f"💳 After Coupon: ₹{price_after_coupon}\n"
            f"🎁 Referral Used: ₹{referral_used}\n"
            f"💵 Main Balance Required: ₹{main_balance_needed}\n"
            f"💰 Your Main Balance: ₹{main_balance}",
            parse_mode="HTML"
        )
        return

    # -----------------------------------------------------
    # CREATE INVITE FIRST
    # -----------------------------------------------------
    #
    # Important:
    # Invite fail hua to balance deduct nahi hoga.
    # -----------------------------------------------------

    invite_link = create_product_invite(
        product_id
    )

    if not invite_link:
        bot.send_message(
            message.chat.id,
            "⚠️ Product access link generate nahi ho saka.\n"
            "Balance deduct nahi hua.\n"
            "Please try again later."
        )
        return

    # -----------------------------------------------------
    # Deduct balance
    # -----------------------------------------------------

    old_main_balance = user["balance"]
    old_ref_balance = user["ref_balance"]

    user["balance"] = (
        old_main_balance - main_balance_needed
    )

    user["ref_balance"] = (
        old_ref_balance - referral_used
    )

    # -----------------------------------------------------
    # Save balance
    # -----------------------------------------------------

    if not save_balance_db(users):
        # Best-effort rollback in memory/database.
        # Telegram DB is not transactional.
        user["balance"] = old_main_balance
        user["ref_balance"] = old_ref_balance

        bot.send_message(
            message.chat.id,
            "⚠️ Balance update failed.\n"
            "Purchase cancelled. Please try again."
        )
        return

    # -----------------------------------------------------
    # Coupon usage
    # -----------------------------------------------------

    if coupon:
        if not update_coupon_usage(
            coupon_code_clean
        ):
            logging.warning(
                "COUPON USAGE UPDATE FAILED: %s",
                coupon_code_clean
            )

    # -----------------------------------------------------
    # Create order
    # -----------------------------------------------------

    order_id = generate_order_id(
        user_id,
        product_id
    )

    order_line = (
        f"ORDER|"
        f"{order_id}|"
        f"{user_id}|"
        f"{product_id}|"
        f"{product['name']}|"
        f"{price_after_coupon}|"
        f"{now_str()}|"
        f"DELIVERED|"
        f"{coupon_code_clean}"
    )

    order_saved = append_order(
        order_line
    )

    if not order_saved:
        logging.error(
            "ORDER SAVE FAILED: %s",
            order_id
        )

    # -----------------------------------------------------
    # SEND ACCESS BUTTON
    # -----------------------------------------------------

    markup = types.InlineKeyboardMarkup()

    markup.add(
        types.InlineKeyboardButton(
            "🟢 JOIN GROUP 🟢",
            url=invite_link
        )
    )

    coupon_text = ""

    if coupon:
        coupon_text = (
            f"\n🎟 Coupon: {coupon_code_clean}"
            f"\n💸 Discount: ₹{coupon_discount}"
        )

    bot.send_message(
        message.chat.id,
        "✅ <b>Purchase Successful!</b>\n\n"
        f"🧾 Order ID: <code>{order_id}</code>\n"
        f"📦 Product: {product['name']}\n"
        f"💰 Original Price: ₹{original_price}"
        f"{coupon_text}\n"
        f"🎁 Referral Used: ₹{referral_used}\n"
        f"💳 Paid From Main Balance: ₹{main_balance_needed}\n\n"
        "🔐 Your private access link is ready.\n"
        "⏱ Link expires in 24 hours.\n"
        "👤 Link can be used by 1 member only.",
        parse_mode="HTML",
        reply_markup=markup
    )


# =========================================================
# /BUY COMMAND
# =========================================================
#
# Hidden/backup command. Normal users should use
# ReplyKeyboard buttons.
# =========================================================

@bot.message_handler(commands=["buy"])
def buy_command(message):
    user_id = message.from_user.id

    if not require_join(message):
        return

    parts = message.text.split()

    if len(parts) < 2:
        bot.send_message(
            message.chat.id,
            "🛍 Hacks menu se product select karo.",
            reply_markup=products_menu()
        )
        return

    product_id = safe_int(parts[1])

    if product_id not in PRODUCTS:
        bot.send_message(
            message.chat.id,
            "❌ Product not found."
        )
        return

    coupon_code = None

    if len(parts) >= 3:
        coupon_code = parts[2].upper()

    send_purchase_confirmation(
        message,
        product_id,
        coupon_code
    )


# =========================================================
# ACCESS PREVIOUS ORDER
# =========================================================

@bot.message_handler(commands=["access"])
def access_order(message):
    user_id = message.from_user.id

    if not require_join(message):
        return

    parts = message.text.split()

    if len(parts) < 2:
        bot.send_message(
            message.chat.id,
            "Usage:\n"
            "<code>/access ORDER_ID</code>",
            parse_mode="HTML"
        )
        return

    requested_order_id = parts[1].strip()

    orders = get_user_orders(user_id)

    if orders is None:
        bot.send_message(
            message.chat.id,
            "⚠️ Orders database unavailable."
        )
        return

    found = None

    for order in orders:
        if order["order_id"] == requested_order_id:
            found = order
            break

    if not found:
        bot.send_message(
            message.chat.id,
            "❌ Order not found."
        )
        return

    product_id = found["product_id"]

    if product_id not in PRODUCTS:
        bot.send_message(
            message.chat.id,
            "❌ Product no longer available."
        )
        return

    # Fresh link again
    invite_link = create_product_invite(
        product_id
    )

    if not invite_link:
        bot.send_message(
            message.chat.id,
            "⚠️ Fresh access link generate nahi ho saka."
        )
        return

    markup = types.InlineKeyboardMarkup()

    markup.add(
        types.InlineKeyboardButton(
            "🟢 JOIN GROUP 🟢",
            url=invite_link
        )
    )

    bot.send_message(
        message.chat.id,
        "🔐 <b>Fresh Access Link</b>\n\n"
        f"🧾 Order: <code>{found['order_id']}</code>\n"
        f"📦 {found['product_name']}\n\n"
        "⏱ Link valid for 24 hours.\n"
        "👤 One member only.",
        parse_mode="HTML",
        reply_markup=markup
    )


# =========================================================
# COUPON APPLY FOR CURRENT PURCHASE
# =========================================================

@bot.message_handler(
    func=lambda message:
        message.text == "🎟 Apply Coupon"
)
def apply_coupon_start(message):
    if not require_join(message):
        return

    user_states[message.from_user.id] = {
        "stage": "coupon"
    }

    bot.send_message(
        message.chat.id,
        "🎟 <b>Enter Coupon Code</b>\n\n"
        "Example:\n"
        "<code>SPEED20</code>\n\n"
        "Cancel karne ke liye /cancel bhejo.",
        parse_mode="HTML"
    )


# =========================================================
# COUPON STATE HANDLER
# =========================================================

def handle_coupon_state(message):
    user_id = message.from_user.id

    state = user_states.get(user_id)

    if not state:
        return False

    if state.get("stage") != "coupon":
        return False

    code = message.text.strip().upper()

    if code == "/cancel":
        user_states.pop(user_id, None)

        bot.send_message(
            message.chat.id,
            "❌ Coupon cancelled.",
            reply_markup=products_menu()
        )
        return True

    coupon = get_coupon(code)

    if not coupon:
        bot.send_message(
            message.chat.id,
            "❌ Invalid coupon.\n"
            "Dobara code bhejo ya /cancel."
        )
        return True

    if coupon.get("active", 0) != 1:
        bot.send_message(
            message.chat.id,
            "❌ Ye coupon inactive hai."
        )
        return True

    if (
        coupon.get("max", 0) > 0
        and coupon.get("used", 0)
        >= coupon.get("max", 0)
    ):
        bot.send_message(
            message.chat.id,
            "❌ Coupon usage limit complete hai."
        )
        return True

    user_states.pop(
        user_id,
        None
    )

    bot.send_message(
        message.chat.id,
        f"✅ Coupon <b>{code}</b> available hai.\n\n"
        f"🎟 Discount: {coupon['pct']}%\n"
        f"📊 Used: {coupon['used']}/{coupon['max']}\n\n"
        "Ab product select karo.\n"
        "Coupon purchase ke time automatically apply karne ke liye "
        "hidden command bhi available hai.",
        parse_mode="HTML",
        reply_markup=products_menu()
    )

    # Store selected coupon temporarily
    user_states[user_id] = {
        "stage": "selected_coupon",
        "coupon": code
    }

    return True


# =========================================================
# PURCHASE WITH SELECTED COUPON
# =========================================================

def get_selected_coupon(user_id):
    state = user_states.get(user_id)

    if not state:
        return None

    if state.get("stage") != "selected_coupon":
        return None

    return state.get("coupon")


def clear_selected_coupon(user_id):
    state = user_states.get(user_id)

    if state and state.get("stage") == "selected_coupon":
        user_states.pop(
            user_id,
            None
        )


# =========================================================
# OVERRIDE PRODUCT PURCHASE TO USE SELECTED COUPON
# =========================================================

def purchase_from_button(message, product_id):
    if not require_join(message):
        return

    coupon = get_selected_coupon(
        message.from_user.id
    )

    send_purchase_confirmation(
        message,
        product_id,
        coupon
    )

    clear_selected_coupon(
        message.from_user.id
    )


# =========================================================
# NOTE:
# The three handlers above call send_purchase_confirmation
# directly. To use selected coupon from keyboard, the
# generic text router in Part 3 will route buttons through
# purchase_from_button().
# =========================================================


# =========================================================
# ADD FUNDS SYSTEM
# =========================================================

def add_funds_start(message):
    if not require_join(message):
        return

    user_states[message.from_user.id] = {
        "stage": "amount"
    }

    bot.send_message(
        message.chat.id,
        "💳 <b>Add Funds</b>\n\n"
        "Kitna amount add karna hai?\n\n"
        "Example: <code>500</code>\n\n"
        "Cancel: /cancel",
        parse_mode="HTML"
    )


def send_payment_instructions(message, amount):
    user_states[message.from_user.id] = {
        "stage": "proof",
        "amount": amount
    }

    qr_path = "qr.jpg"

    text = (
        "💳 <b>Payment Instructions</b>\n\n"
        f"💰 Amount: <b>₹{amount}</b>\n\n"
        "1️⃣ Neeche QR scan karke payment karo.\n"
        "2️⃣ Payment ke baad UTR / Transaction ID "
        "ya payment screenshot bhejo.\n"
        "3️⃣ Admin verification ke baad balance add hoga.\n\n"
        "👑 Payment Help: @SpeedFistt\n\n"
        "⚠️ Payment karne se pehle amount verify kar lena."
    )

    try:
        if os.path.exists(qr_path):
            with open(qr_path, "rb") as photo:
                bot.send_photo(
                    message.chat.id,
                    photo,
                    caption=text,
                    parse_mode="HTML"
                )
        else:
            bot.send_message(
                message.chat.id,
                text + "\n\n⚠️ QR file abhi available nahi hai.",
                parse_mode="HTML"
            )

    except Exception:
        bot.send_message(
            message.chat.id,
            text,
            parse_mode="HTML"
        )

    bot.send_message(
        message.chat.id,
        "📸 Payment proof bhejo:\n"
        "• UTR / Transaction ID text mein\n"
        "• Ya screenshot/photo\n\n"
        "Cancel: /cancel"
    )


def handle_add_funds_amount(message):
    user_id = message.from_user.id

    state = user_states.get(user_id)

    if not state or state.get("stage") != "amount":
        return False

    text = message.text.strip()

    if text.lower() == "/cancel":
        user_states.pop(user_id, None)

        bot.send_message(
            message.chat.id,
            "❌ Add Funds cancelled.",
            reply_markup=main_menu(user_id)
        )
        return True

    amount = safe_int(text)

    if amount <= 0:
        bot.send_message(
            message.chat.id,
            "❌ Valid amount bhejo.\n"
            "Example: 500"
        )
        return True

    if amount > 100000:
        bot.send_message(
            message.chat.id,
            "❌ Maximum single payment ₹100000 hai."
        )
        return True

    send_payment_instructions(
        message,
        amount
    )

    return True


def handle_add_funds_proof(message):
    user_id = message.from_user.id
    state = user_states.get(user_id)
    if not state or state.get("stage") != "proof":
        return False

    amount = safe_int(state.get("amount"))
    if amount <= 0:
        user_states.pop(user_id, None)
        bot.send_message(message.chat.id, "⚠️ Payment request expired. Please start Add Funds again.")
        return True

    request_id = str(int(time.time() * 1000))
    pending_funding[(user_id, request_id)] = {"amount": amount, "created_at": now_str()}

    try:
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("✅ Approve", callback_data=f"fund_approve:{user_id}:{request_id}"),
            types.InlineKeyboardButton("❌ Decline", callback_data=f"fund_decline:{user_id}:{request_id}")
        )

        bot.send_message(
            ADMIN_ID,
            "💳 <b>NEW FUNDING REQUEST</b>\n\n"
            f"👤 User ID: <code>{user_id}</code>\n"
            f"💰 Amount: ₹{amount}\n"
            f"📅 Time: {now_str()}\n\n"
            "Payment proof neeche attached hai.\n"
            "Verify karke button use karein:",
            parse_mode="HTML", reply_markup=markup
        )
        bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
        bot.send_message(
            message.chat.id,
            "✅ Payment proof received.\n\n"
            f"💰 Amount: ₹{amount}\n"
            "👨‍💼 Admin verification pending hai.\n\n"
            "Verification ke baad balance update ho jayega."
        )
        user_states.pop(user_id, None)
    except Exception:
        pending_funding.pop((user_id, request_id), None)
        logging.exception("FUNDING PROOF ERROR")
        bot.send_message(message.chat.id, "⚠️ Proof send nahi ho saka.\nPlease try again.")
    return True


# =========================================================
# ADMIN: FUNDING APPROVE / DECLINE
# =========================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("fund_approve:") or call.data.startswith("fund_decline:")
)
def funding_decision_callback(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Admin only.", show_alert=True)
        return

    parts = call.data.split(":")
    if len(parts) != 3:
        bot.answer_callback_query(call.id, "⚠️ Invalid request.", show_alert=True)
        return

    action, user_id_text, request_id = parts
    target_user_id = safe_int(user_id_text)
    request = pending_funding.get((target_user_id, request_id))

    if not request:
        bot.answer_callback_query(call.id, "⚠️ Request already processed or expired.", show_alert=True)
        return

    amount = safe_int(request.get("amount"))

    if action == "fund_approve":
        success, result = admin_add_balance(target_user_id, amount)
        if not success:
            bot.answer_callback_query(call.id, f"❌ {result}", show_alert=True)
            return

        pending_funding.pop((target_user_id, request_id), None)
        bot.answer_callback_query(call.id, "✅ Payment approved.", show_alert=True)
        try:
            bot.edit_message_reply_markup(ADMIN_ID, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        try:
            bot.send_message(
                target_user_id,
                "✅ <b>Payment Approved!</b>\n\n"
                f"💰 ₹{amount} balance me add kar diya gaya hai.\n"
                f"💳 Current Balance: ₹{result}", parse_mode="HTML"
            )
        except Exception:
            logging.exception("FUNDING APPROVE USER NOTIFY ERROR")
        return

    pending_funding.pop((target_user_id, request_id), None)
    bot.answer_callback_query(call.id, "❌ Payment declined.", show_alert=True)
    try:
        bot.edit_message_reply_markup(ADMIN_ID, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    try:
        bot.send_message(
            target_user_id,
            "❌ <b>Payment Declined</b>\n\n"
            f"💰 Requested Amount: ₹{amount}\n"
            "Payment proof verify nahi ho saka.\n\n"
            "Agar payment genuinely kiya hai, correct UTR/screenshot ke saath dobara Add Funds request bhejo.",
            parse_mode="HTML"
        )
    except Exception:
        logging.exception("FUNDING DECLINE USER NOTIFY ERROR")


# =========================================================
# ADMIN: ADD BALANCE
# =========================================================

@db_locked
def admin_add_balance(user_id, amount):
    users = load_balance_db()

    if users is None:
        return False, "Database unavailable."

    user = get_or_create_user(
        users,
        user_id
    )

    user["balance"] += amount

    if not save_balance_db(users):
        return False, "Database save failed."

    return True, user["balance"]


@bot.message_handler(commands=["add"])
def admin_add_command(message):
    if not is_admin(message.from_user.id):
        bot.send_message(
            message.chat.id,
            "❌ Admin only."
        )
        return

    parts = message.text.split()

    if len(parts) != 3:
        bot.send_message(
            message.chat.id,
            "Usage:\n"
            "<code>/add USER_ID AMOUNT</code>\n\n"
            "Example:\n"
            "<code>/add 123456789 500</code>",
            parse_mode="HTML"
        )
        return

    target_user_id = safe_int(parts[1])
    amount = safe_int(parts[2])

    if target_user_id <= 0:
        bot.send_message(
            message.chat.id,
            "❌ Invalid User ID."
        )
        return

    if amount <= 0:
        bot.send_message(
            message.chat.id,
            "❌ Invalid amount."
        )
        return

    success, result = admin_add_balance(
        target_user_id,
        amount
    )

    if not success:
        bot.send_message(
            message.chat.id,
            f"❌ {result}"
        )
        return

    for key, pending in list(pending_funding.items()):
        pending_user_id, pending_request_id = key
        if pending_user_id == target_user_id and safe_int(pending.get("amount")) == amount:
            pending_funding.pop(key, None)
            break

    bot.send_message(
        message.chat.id,
        "✅ <b>Balance Added</b>\n\n"
        f"👤 User ID: <code>{target_user_id}</code>\n"
        f"💰 Added: ₹{amount}\n"
        f"💳 New Balance: ₹{result}",
        parse_mode="HTML"
    )

    # Notify user
    try:
        bot.send_message(
            target_user_id,
            "🎉 <b>Balance Updated</b>\n\n"
            f"💰 Added: ₹{amount}\n"
            f"💳 New Balance: ₹{result}",
            parse_mode="HTML"
        )
    except Exception:
        logging.warning(
            "USER BALANCE NOTIFICATION FAILED: %s",
            target_user_id
        )


# =========================================================
# ADMIN PANEL
# =========================================================

def show_admin_panel(message):
    if not is_admin(message.from_user.id):
        bot.send_message(
            message.chat.id,
            "❌ Admin only."
        )
        return

    bot.send_message(
        message.chat.id,
        "👨‍💼 <b>Admin Panel</b>\n\n"
        "👑 Owner: @SpeedFistt\n\n"
        "Neeche option select karo.",
        parse_mode="HTML",
        reply_markup=admin_menu()
    )


# =========================================================
# ADMIN ADD BALANCE BUTTON
# =========================================================

def admin_add_balance_start(message):
    if not is_admin(message.from_user.id):
        return

    user_states[message.from_user.id] = {
        "stage": "admin_add"
    }

    bot.send_message(
        message.chat.id,
        "💳 <b>Add Balance</b>\n\n"
        "Format bhejo:\n"
        "<code>USER_ID AMOUNT</code>\n\n"
        "Example:\n"
        "<code>123456789 500</code>\n\n"
        "Cancel: /cancel",
        parse_mode="HTML"
    )


def handle_admin_add_state(message):
    admin_id = message.from_user.id

    if not is_admin(admin_id):
        return False

    state = user_states.get(admin_id)

    if not state or state.get("stage") != "admin_add":
        return False

    if message.text.strip().lower() == "/cancel":
        user_states.pop(admin_id, None)

        bot.send_message(
            message.chat.id,
            "❌ Cancelled.",
            reply_markup=admin_menu()
        )
        return True

    parts = message.text.strip().split()

    if len(parts) != 2:
        bot.send_message(
            message.chat.id,
            "❌ Format:\n"
            "<code>USER_ID AMOUNT</code>",
            parse_mode="HTML"
        )
        return True

    target_user_id = safe_int(parts[0])
    amount = safe_int(parts[1])

    if target_user_id <= 0 or amount <= 0:
        bot.send_message(
            message.chat.id,
            "❌ Invalid User ID ya amount."
        )
        return True

    success, result = admin_add_balance(
        target_user_id,
        amount
    )

    if not success:
        bot.send_message(
            message.chat.id,
            f"❌ {result}"
        )
        return True

    user_states.pop(
        admin_id,
        None
    )

    bot.send_message(
        message.chat.id,
        "✅ <b>Balance Added</b>\n\n"
        f"👤 User: <code>{target_user_id}</code>\n"
        f"💰 Added: ₹{amount}\n"
        f"💳 New Balance: ₹{result}",
        parse_mode="HTML",
        reply_markup=admin_menu()
    )

    try:
        bot.send_message(
            target_user_id,
            "🎉 <b>Balance Added</b>\n\n"
            f"💰 Amount: ₹{amount}\n"
            f"💳 New Balance: ₹{result}",
            parse_mode="HTML"
        )
    except Exception:
        pass

    return True


# =========================================================
# ADMIN STATISTICS
# =========================================================

def show_statistics(message):
    if not is_admin(message.from_user.id):
        bot.send_message(
            message.chat.id,
            "❌ Admin only."
        )
        return

    users = load_balance_db()

    if users is None:
        bot.send_message(
            message.chat.id,
            "⚠️ Balance database unavailable."
        )
        return

    orders_text = load_orders_db()

    if orders_text is None:
        bot.send_message(
            message.chat.id,
            "⚠️ Orders database unavailable."
        )
        return

    total_users = len(users)

    total_main_balance = sum(
        data.get("balance", 0)
        for data in users.values()
    )

    total_ref_balance = sum(
        data.get("ref_balance", 0)
        for data in users.values()
    )

    orders = []

    for line in orders_text.splitlines():
        if not line.startswith("ORDER|"):
            continue

        parts = line.split("|")

        if len(parts) < 9:
            continue

        orders.append(parts)

    total_orders = len(orders)

    total_sales = sum(
        safe_int(order[5])
        for order in orders
    )

    today = datetime.now().date()
    week_start = today - timedelta(days=6)

    today_orders = 0
    today_sales = 0
    week_orders = 0
    week_sales = 0

    for order in orders:
        try:
            order_date = datetime.strptime(
                order[6].strip(),
                "%Y-%m-%d %H:%M:%S"
            ).date()
        except Exception:
            continue

        amount = safe_int(order[5])

        if order_date == today:
            today_orders += 1
            today_sales += amount

        if order_date >= week_start:
            week_orders += 1
            week_sales += amount

    product_counts = {
        1: 0,
        2: 0,
        3: 0
    }

    for order in orders:
        product_id = safe_int(order[3])

        if product_id in product_counts:
            product_counts[product_id] += 1

    bot.send_message(
        message.chat.id,
        "📊 <b>Statistics</b>\n\n"
        f"👥 Users: {total_users}\n"
        f"📦 Orders: {total_orders}\n"
        f"💰 Total Sales: ₹{total_sales}\n"
        f"📅 Today: {today_orders} orders / ₹{today_sales}\n"
        f"📈 Last 7 Days: {week_orders} orders / ₹{week_sales}\n"
        f"💳 User Main Balances: ₹{total_main_balance}\n"
        f"🎁 Referral Balances: ₹{total_ref_balance}\n\n"
        f"1️⃣ Product A Orders: {product_counts[1]}\n"
        f"2️⃣ Product B Orders: {product_counts[2]}\n"
        f"3️⃣ Product C Orders: {product_counts[3]}",
        parse_mode="HTML"
    )


# =========================================================
# COUPON ADMIN HELPERS
# =========================================================

def create_coupon(
    code,
    pct,
    max_uses
):
    code = code.upper().strip()

    if not re.fullmatch(
        r"[A-Z0-9_-]{3,30}",
        code
    ):
        return False, "Invalid coupon code."

    if pct < 1 or pct > 100:
        return False, "Discount 1-100% ke beech hona chahiye."

    if max_uses < 1:
        return False, "Max uses minimum 1 hona chahiye."

    text = load_orders_db()

    if text is None:
        return False, "Orders database unavailable."

    coupons = parse_coupons(text)

    if code in coupons:
        return False, "Coupon already exists."

    line = (
        f"COUPON|{code}|{pct}|"
        f"{max_uses}|0|1"
    )

    lines = [
        x.strip()
        for x in text.splitlines()
        if x.strip()
    ]

    lines.append(line)

    if not save_orders_db(
        "\n".join(lines)
    ):
        return False, "Database save failed."

    return True, "Coupon created."


@bot.message_handler(commands=["createcoupon"])
def create_coupon_command(message):
    if not is_admin(message.from_user.id):
        bot.send_message(
            message.chat.id,
            "❌ Admin only."
        )
        return

    parts = message.text.split()

    if len(parts) != 4:
        bot.send_message(
            message.chat.id,
            "Usage:\n"
            "<code>/createcoupon CODE PERCENT MAX_USES</code>\n\n"
            "Example:\n"
            "<code>/createcoupon SPEED20 20 10</code>",
            parse_mode="HTML"
        )
        return

    code = parts[1]
    pct = safe_int(parts[2])
    max_uses = safe_int(parts[3])

    success, result = create_coupon(
        code,
        pct,
        max_uses
    )

    if success:
        bot.send_message(
            message.chat.id,
            "✅ <b>Coupon Created</b>\n\n"
            f"🎟 Code: <code>{code.upper()}</code>\n"
            f"💸 Discount: {pct}%\n"
            f"📊 Max Uses: {max_uses}",
            parse_mode="HTML"
        )
    else:
        bot.send_message(
            message.chat.id,
            f"❌ {result}"
        )


@bot.message_handler(commands=["listcoupons"])
def list_coupons_command(message):
    if not is_admin(message.from_user.id):
        bot.send_message(
            message.chat.id,
            "❌ Admin only."
        )
        return

    text = load_orders_db()

    if text is None:
        bot.send_message(
            message.chat.id,
            "⚠️ Orders database unavailable."
        )
        return

    coupons = parse_coupons(text)

    if not coupons:
        bot.send_message(
            message.chat.id,
            "🎟 No coupons found."
        )
        return

    lines = [
        "🎟 <b>Coupons</b>",
        ""
    ]

    for code, data in coupons.items():
        status = (
            "🟢 ACTIVE"
            if data["active"] == 1
            else "🔴 DISABLED"
        )

        lines.append(
            f"🎟 <code>{code}</code>\n"
            f"💸 Discount: {data['pct']}%\n"
            f"📊 Used: {data['used']}/{data['max']}\n"
            f"📌 {status}\n"
        )

    bot.send_message(
        message.chat.id,
        "\n".join(lines),
        parse_mode="HTML"
    )


@bot.message_handler(commands=["disablecoupon"])
def disable_coupon_command(message):
    if not is_admin(message.from_user.id):
        bot.send_message(
            message.chat.id,
            "❌ Admin only."
        )
        return

    parts = message.text.split()

    if len(parts) != 2:
        bot.send_message(
            message.chat.id,
            "Usage:\n"
            "<code>/disablecoupon CODE</code>",
            parse_mode="HTML"
        )
        return

    code = parts[1].upper()

    text = load_orders_db()

    if text is None:
        bot.send_message(
            message.chat.id,
            "⚠️ Orders database unavailable."
        )
        return

    found = False
    lines = []

    for line in text.splitlines():
        if line.startswith("COUPON|"):
            parts2 = line.split("|")

            if (
                len(parts2) >= 6
                and parts2[1].upper() == code
            ):
                parts2[5] = "0"
                line = "|".join(parts2)
                found = True

        lines.append(line)

    if not found:
        bot.send_message(
            message.chat.id,
            "❌ Coupon not found."
        )
        return

    if save_orders_db("\n".join(lines)):
        bot.send_message(
            message.chat.id,
            f"✅ Coupon <code>{code}</code> disabled.",
            parse_mode="HTML"
        )
    else:
        bot.send_message(
            message.chat.id,
            "❌ Database save failed."
        )


# =========================================================
# CANCEL
# =========================================================

@bot.message_handler(commands=["cancel"])
def cancel_command(message):
    user_states.pop(
        message.from_user.id,
        None
    )

    if is_admin(message.from_user.id):
        markup = admin_menu()
    else:
        markup = main_menu(
            message.from_user.id
        )

    bot.send_message(
        message.chat.id,
        "❌ Current action cancelled.",
        reply_markup=markup
    )


# =========================================================
# PRODUCTS BUTTON
# =========================================================

@bot.message_handler(
    func=lambda message:
        message.text == "🛍 Hacks"
)
def products_button(message):
    if not require_join(message):
        return

    send_products(
        message.chat.id
    )


# =========================================================
# BALANCE BUTTON
# =========================================================

@bot.message_handler(
    func=lambda message:
        message.text == "💰 Balance"
)
def balance_button(message):
    if not require_join(message):
        return

    show_balance(
        message.chat.id,
        message.from_user.id
    )


# =========================================================
# ADD FUNDS BUTTON
# =========================================================

@bot.message_handler(
    func=lambda message:
        message.text == "💳 Add Funds"
)
def add_funds_button(message):
    add_funds_start(message)


# =========================================================
# MY ORDERS BUTTON
# =========================================================

@bot.message_handler(
    func=lambda message:
        message.text == "📜 My Orders"
)
def orders_button(message):
    if not require_join(message):
        return

    show_orders(message)


# =========================================================
# PROFILE BUTTON
# =========================================================

@bot.message_handler(
    func=lambda message:
        message.text == "👤 Profile"
)
def profile_button(message):
    if not require_join(message):
        return

    show_profile(message)


# =========================================================
# REFERRAL BUTTON
# =========================================================

@bot.message_handler(
    func=lambda message:
        message.text == "👥 Referral"
)
def referral_button(message):
    if not require_join(message):
        return

    show_referral(message)


# =========================================================
# ADMIN PANEL BUTTON
# =========================================================

@bot.message_handler(
    func=lambda message:
        message.text == "👨‍💼 Admin Panel"
)
def admin_panel_button(message):
    show_admin_panel(message)


# =========================================================
# ADMIN ADD BALANCE BUTTON
# =========================================================

@bot.message_handler(
    func=lambda message:
        message.text == "💳 Add Balance"
)
def admin_add_balance_button(message):
    admin_add_balance_start(message)


# =========================================================
# ADMIN STATISTICS BUTTON
# =========================================================

@bot.message_handler(
    func=lambda message:
        message.text == "📊 Statistics"
)
def statistics_button(message):
    show_statistics(message)


# =========================================================
# MAIN MENU BUTTON
# =========================================================

@bot.message_handler(
    func=lambda message:
        message.text == "🏠 Main Menu"
)
def main_menu_button(message):
    user_states.pop(
        message.from_user.id,
        None
    )

    if not require_join(message):
        return

    bot.send_message(
        message.chat.id,
        "🏠 <b>Main Menu</b>",
        parse_mode="HTML",
        reply_markup=main_menu(
            message.from_user.id
        )
    )


# =========================================================
# STATE ROUTER
# =========================================================
#
# Ye handler text messages ke states ko handle karta hai.
# Isko product/button handlers ke baad rakha gaya hai.
# =========================================================

@bot.message_handler(
    func=lambda message:
        message.content_type == "text"
        and not message.text.startswith("/")
)
def text_state_router(message):
    user_id = message.from_user.id

    text = message.text.strip()

    # -----------------------------------------------------
    # Admin state
    # -----------------------------------------------------

    if is_admin(user_id):
        if handle_admin_add_state(message):
            return

    # -----------------------------------------------------
    # Add funds amount
    # -----------------------------------------------------

    if handle_add_funds_amount(message):
        return

    # -----------------------------------------------------
    # Add funds proof
    # -----------------------------------------------------

    if handle_add_funds_proof(message):
        return

    # -----------------------------------------------------
    # Coupon
    # -----------------------------------------------------

    state = user_states.get(user_id)

    if state and state.get("stage") == "coupon":
        if handle_coupon_state(message):
            return

    # -----------------------------------------------------
    # Selected coupon + product purchase
    # -----------------------------------------------------

    if text == "🛒 Buy Product 1":
        purchase_from_button(
            message,
            1
        )
        return

    if text == "🛒 Buy Product 2":
        purchase_from_button(
            message,
            2
        )
        return

    if text == "🛒 Buy Product 3":
        purchase_from_button(
            message,
            3
        )
        return

    # -----------------------------------------------------
    # Unknown text
    # -----------------------------------------------------

    bot.send_message(
        message.chat.id,
        "👇 Menu se option select karo.",
        reply_markup=main_menu(user_id)
    )


# =========================================================
# PHOTO PROOF HANDLER
# =========================================================

@bot.message_handler(
    content_types=["photo"]
)
def photo_handler(message):
    # Use the same funding workflow as text/UTR proofs.
    # This keeps Approve/Decline buttons consistent for screenshots too.
    handle_add_funds_proof(message)


# =========================================================
# /BALANCE
# =========================================================

@bot.message_handler(commands=["balance"])
def balance_command(message):
    if not require_join(message):
        return

    show_balance(
        message.chat.id,
        message.from_user.id
    )


# =========================================================
# /PRODUCTS
# =========================================================

@bot.message_handler(commands=["products"])
def products_command(message):
    if not require_join(message):
        return

    send_products(
        message.chat.id
    )


# =========================================================
# /PING
# =========================================================

@bot.message_handler(commands=["ping"])
def ping_command(message):
    bot.send_message(
        message.chat.id,
        "🏓 Pong!"
    )

@bot.message_handler(commands=["checkjoin"])
def checkjoin_command(message):
    user_id = message.from_user.id

    lines = [
        "🔍 <b>Join Debug</b>",
        f"User ID: <code>{user_id}</code>",
        ""
    ]

    for channel in MANDATORY_CHANNELS:
        try:
            member = bot.get_chat_member(
                chat_id=channel["id"],
                user_id=user_id
            )

            lines.append(
                f"{channel['name']}: "
                f"<b>{member.status}</b>"
            )

        except Exception as e:
            lines.append(
                f"{channel['name']}: "
                f"❌ <code>{str(e)[:250]}</code>"
            )

    bot.send_message(
        message.chat.id,
        "\n".join(lines),
        parse_mode="HTML"
    )

# =========================================================
# WEBHOOK
# =========================================================

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_data().decode("utf-8")

        update = telebot.types.Update.de_json(data)

        # Process update outside the Flask request.
        threading.Thread(
            target=process_update_background,
            args=(update,),
            daemon=True
        ).start()

        return "OK", 200

    except Exception:
        logging.exception("WEBHOOK ERROR")
        return "ERROR", 500


# =========================================================
# SET WEBHOOK
# =========================================================

def setup_webhook():
    try:
        webhook_url = f"{WEBHOOK_URL.rstrip('/')}/webhook"

        bot.remove_webhook()
        time.sleep(1)

        result = bot.set_webhook(
            url=webhook_url,
            drop_pending_updates=False
        )

        logging.info("WEBHOOK SET: %s", result)

    except Exception:
        logging.exception("WEBHOOK SETUP ERROR")

# =========================================================
# START APP
# =========================================================

setup_webhook()

if __name__ == "__main__":
    port = int(
        os.getenv("PORT", "10000")
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
