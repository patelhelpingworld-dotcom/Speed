```python
import os
import re
import time
import secrets
import logging
import threading

import telebot
from telebot import types


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_NEW_BOT_TOKEN")

# Telegram user ID of the only admin allowed to /add
ADMIN_ID = int(os.getenv("ADMIN_ID", "1006157952"))

# Private channel ID
# Example: -1001234567890
CHANNEL_ID = int(
    os.getenv("CHANNEL_ID", "-1000000000000")
)

# Message ID of the BALANCE DATABASE message
# Create one message manually in your private channel.
BALANCE_MESSAGE_ID = int(
    os.getenv("BALANCE_MESSAGE_ID", "1")
)

QR_CODE_URL = (
    "https://i.ibb.co/7JzK1hRv/"
    "IMG-20260913-223730-495.jpg"
)


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("SpeedFistt")


# =========================================================
# BOT
# =========================================================

bot = telebot.TeleBot(BOT_TOKEN)

# Prevent two balance operations from modifying the
# balance message at exactly the same time.
balance_lock = threading.Lock()


# =========================================================
# BASIC HELPERS
# =========================================================

def generate_txn_id():
    return "SF-" + secrets.token_hex(5).upper()


def clean_number(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# =========================================================
# CHANNEL DATABASE
# =========================================================

def get_balance_database_text():
    """
    Reads the fixed balance message from the private channel.
    """

    message = bot.forward_message(
        chat_id=CHANNEL_ID,
        from_chat_id=CHANNEL_ID,
        message_id=BALANCE_MESSAGE_ID
    )

    # The forwarded message contains the original text.
    # Delete the temporary forwarded copy afterwards.
    try:
        bot.delete_message(
            CHANNEL_ID,
            message.message_id
        )
    except Exception:
        pass

    return message.text or ""


def read_balances():
    """
    Expected balance database format:

    SPEEDFISTT BALANCE DATABASE

    USER: 123456789 | BALANCE: 500
    USER: 987654321 | BALANCE: 1200
    """

    text = get_balance_database_text()

    balances = {}

    pattern = r"USER:\s*(\d+)\s*\|\s*BALANCE:\s*(-?\d+)"

    for match in re.finditer(pattern, text):
        user_id = int(match.group(1))
        balance = int(match.group(2))

        balances[user_id] = balance

    return balances


def create_balance_database_text(balances):
    """
    Creates the complete balance message text.
    """

    lines = [
        "💰 SPEEDFISTT BALANCE DATABASE",
        "",
        "⚠️ DO NOT EDIT THIS MESSAGE MANUALLY",
        ""
    ]

    if not balances:
        lines.append("NO USERS YET")
    else:

        for user_id in sorted(balances):

            lines.append(
                f"USER: {user_id} | BALANCE: {balances[user_id]}"
            )

    return "\n".join(lines)


def save_balances(balances):
    """
    Updates the fixed balance database message.
    """

    new_text = create_balance_database_text(
        balances
    )

    bot.edit_message_text(
        chat_id=CHANNEL_ID,
        message_id=BALANCE_MESSAGE_ID,
        text=new_text
    )


def get_user_balance(user_id):

    with balance_lock:

        balances = read_balances()

        return balances.get(user_id, 0)


def update_user_balance(
    user_id,
    amount,
    operation
):
    """
    operation:
        CREDIT
        DEBIT

    Returns:
        success, new_balance
    """

    with balance_lock:

        balances = read_balances()

        current_balance = balances.get(
            user_id,
            0
        )

        if operation == "CREDIT":

            new_balance = (
                current_balance + amount
            )

        elif operation == "DEBIT":

            if current_balance < amount:
                return False, current_balance

            new_balance = (
                current_balance - amount
            )

        else:

            raise ValueError(
                "Invalid balance operation"
            )

        balances[user_id] = new_balance

        save_balances(balances)

        return True, new_balance


# =========================================================
# CHANNEL AUDIT LOG
# =========================================================

def send_audit_log(
    txn_type,
    user_id,
    amount,
    new_balance,
    product="",
    note=""
):

    txn_id = generate_txn_id()

    if txn_type == "CREDIT":
        icon = "🟢"
    else:
        icon = "🔴"

    text = (
        f"{icon} SPEEDFISTT TRANSACTION\n\n"
        f"TXN: {txn_id}\n"
        f"TYPE: {txn_type}\n"
        f"USER: {user_id}\n"
        f"AMOUNT: ₹{amount}\n"
        f"BALANCE: ₹{new_balance}\n"
    )

    if product:
        text += f"PRODUCT: {product}\n"

    if note:
        text += f"NOTE: {note}\n"

    try:

        bot.send_message(
            CHANNEL_ID,
            text
        )

    except Exception:

        logger.exception(
            "Could not send audit log"
        )

    return txn_id


# =========================================================
# KEYBOARDS
# =========================================================

def main_menu():

    markup = types.ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    markup.row(
        types.KeyboardButton("BALANCE ✅"),
        types.KeyboardButton("ADD FUND ✅")
    )

    markup.row(
        types.KeyboardButton(
            "SPEEDFISTT PRODUCTS"
        )
    )

    return markup


def products_menu():

    markup = types.ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    markup.row(
        types.KeyboardButton(
            "🛒 PRODUCT 1 (₹399)"
        )
    )

    markup.row(
        types.KeyboardButton(
            "🛒 PRODUCT 2 (₹599)"
        )
    )

    markup.row(
        types.KeyboardButton(
            "वापस जाएँ 🔙"
        )
    )

    return markup


# =========================================================
# START
# =========================================================

@bot.message_handler(commands=["start"])
def start_command(message):

    bot.send_message(
        message.chat.id,
        (
            "👋 *Welcome to SpeedFistt Store!*\n\n"
            "🛍️ नीचे दिए गए menu से आगे बढ़ें।"
        ),
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


# =========================================================
# BALANCE
# =========================================================

@bot.message_handler(commands=["balance"])
def balance_command(message):

    try:

        balance = get_user_balance(
            message.from_user.id
        )

        bot.send_message(
            message.chat.id,
            (
                "💰 *Your Balance*\n\n"
                f"₹ *{balance}*"
            ),
            parse_mode="Markdown"
        )

    except Exception:

        logger.exception(
            "Balance check failed"
        )

        bot.send_message(
            message.chat.id,
            "❌ Balance check में error आया।"
        )


# =========================================================
# ADMIN ADD
# =========================================================

@bot.message_handler(commands=["add"])
def add_command(message):

    # -----------------------------------------------------
    # ADMIN CHECK
    # -----------------------------------------------------

    if message.from_user.id != ADMIN_ID:

        bot.send_message(
            message.chat.id,
            "❌ आपको इस command की permission नहीं है।"
        )

        return

    # -----------------------------------------------------
    # PARSE
    # -----------------------------------------------------

    args = message.text.split()

    if len(args) != 3:

        bot.send_message(
            message.chat.id,
            (
                "⚠️ *Correct Format:*\n\n"
                "`/add USER_ID AMOUNT`\n\n"
                "Example:\n"
                "`/add 123456789 500`"
            ),
            parse_mode="Markdown"
        )

        return

    target_user = clean_number(args[1])
    amount = clean_number(args[2])

    if target_user is None:

        bot.send_message(
            message.chat.id,
            "❌ Invalid User ID."
        )

        return

    if amount is None:

        bot.send_message(
            message.chat.id,
            "❌ Invalid amount."
        )

        return

    if target_user <= 0:

        bot.send_message(
            message.chat.id,
            "❌ Invalid User ID."
        )

        return

    if amount <= 0:

        bot.send_message(
            message.chat.id,
            "❌ Amount 0 से ज्यादा होना चाहिए।"
        )

        return

    if amount > 1_000_000:

        bot.send_message(
            message.chat.id,
            "❌ Maximum single credit ₹10,00,000 है।"
        )

        return

    # -----------------------------------------------------
    # CREDIT
    # -----------------------------------------------------

    try:

        success, new_balance = (
            update_user_balance(
                target_user,
                amount,
                "CREDIT"
            )
        )

        if not success:

            bot.send_message(
                message.chat.id,
                "❌ Balance update failed."
            )

            return

        txn_id = send_audit_log(
            "CREDIT",
            target_user,
            amount,
            new_balance,
            note=f"Admin {ADMIN_ID}"
        )

        bot.send_message(
            message.chat.id,
            (
                "✅ *Balance Added*\n\n"
                f"👤 User: `{target_user}`\n"
                f"💵 Added: *₹{amount}*\n"
                f"💰 New Balance: *₹{new_balance}*\n"
                f"🧾 TXN: `{txn_id}`"
            ),
            parse_mode="Markdown"
        )

        # -------------------------------------------------
        # USER NOTIFICATION
        # -------------------------------------------------

        try:

            bot.send_message(
                target_user,
                (
                    "🎉 *Balance Added!*\n\n"
                    f"💵 Added: *₹{amount}*\n"
                    f"💰 New Balance: *₹{new_balance}*\n"
                    f"🧾 TXN: `{txn_id}`"
                ),
                parse_mode="Markdown"
            )

        except Exception as e:

            logger.warning(
                "User notification failed: %s",
                e
            )

    except Exception:

        logger.exception(
            "Admin balance add failed"
        )

        bot.send_message(
            message.chat.id,
            "❌ Balance update में error आया।"
        )


# =========================================================
# FUND INFORMATION
# =========================================================

def send_fund_info(message):

    user_id = message.from_user.id

    caption = (
        "📌 *Manual Fund Add Process*\n\n"
        "1. QR code scan करें।\n"
        "2. Payment complete करें।\n"
        "3. Screenshot admin को भेजें।\n\n"
        f"🔑 आपकी User ID: `{user_id}`\n"
        "📩 Screenshot @SpeedFistt पर भेजें।"
    )

    try:

        bot.send_photo(
            message.chat.id,
            QR_CODE_URL,
            caption=caption,
            parse_mode="Markdown"
        )

    except Exception:

        logger.exception(
            "QR image sending failed"
        )

        bot.send_message(
            message.chat.id,
            caption,
            parse_mode="Markdown"
        )


# =========================================================
# PURCHASE
# =========================================================

def process_purchase(
    message,
    product_name,
    price
):

    user_id = message.from_user.id

    try:

        success, new_balance = (
            update_user_balance(
                user_id,
                price,
                "DEBIT"
            )
        )

        if not success:

            bot.send_message(
                message.chat.id,
                (
                    "❌ *Insufficient Balance*\n\n"
                    f"💵 Required: ₹{price}\n"
                    f"💰 Your Balance: ₹{new_balance}\n\n"
                    "ADD FUND से balance add करें।"
                ),
                parse_mode="Markdown"
            )

            return

        txn_id = send_audit_log(
            "DEBIT",
            user_id,
            price,
            new_balance,
            product=product_name
        )

        bot.send_message(
            message.chat.id,
            (
                "✅ *Purchase Successful!*\n\n"
                f"📦 Product: *{product_name}*\n"
                f"💸 Paid: *₹{price}*\n"
                f"💰 Remaining: *₹{new_balance}*\n"
                f"🧾 TXN: `{txn_id}`\n\n"
                "📦 Digital product delivery "
                "यहाँ configure की जा सकती है।"
            ),
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

    except Exception:

        logger.exception(
            "Purchase failed"
        )

        bot.send_message(
            message.chat.id,
            "❌ Purchase process में error आया।"
        )


# =========================================================
# MAIN MESSAGE HANDLER
# =========================================================

@bot.message_handler(
    func=lambda message: True
)
def message_handler(message):

    text = message.text or ""

    if text == "BALANCE ✅":

        try:

            balance = get_user_balance(
                message.from_user.id
            )

            bot.send_message(
                message.chat.id,
                (
                    "💰 *Current Balance*\n\n"
                    f"₹ *{balance}*"
                ),
                parse_mode="Markdown"
            )

        except Exception:

            logger.exception(
                "Balance button failed"
            )

    elif text == "ADD FUND ✅":

        send_fund_info(message)

    elif text == "SPEEDFISTT PRODUCTS":

        bot.send_message(
            message.chat.id,
            (
                "🛍️ *SpeedFistt Products*\n\n"
                "Product select करें:"
            ),
            parse_mode="Markdown",
            reply_markup=products_menu()
        )

    elif text == "🛒 PRODUCT 1 (₹399)":

        process_purchase(
            message,
            "SpeedFistt Product 1",
            399
        )

    elif text == "🛒 PRODUCT 2 (₹599)":

        process_purchase(
            message,
            "SpeedFistt Product 2",
            599
        )

    elif text == "वापस जाएँ 🔙":

        bot.send_message(
            message.chat.id,
            "🔙 *Main Menu*",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )


# =========================================================
# START
# =========================================================

def main():

    logger.info(
        "SpeedFistt Bot starting..."
    )

    print(
        "🤖 SpeedFistt Bot is running..."
    )

    bot.infinity_polling(
        skip_pending=True,
        timeout=30,
        long_polling_timeout=30
    )


if __name__ == "__main__":
    main()
```
