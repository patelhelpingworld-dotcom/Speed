```python
import os
import logging
import secrets
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor
import telebot
from telebot import types


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", "1006157952"))

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
# VALIDATE CONFIG
# =========================================================

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing.")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is missing.")


bot = telebot.TeleBot(BOT_TOKEN)


# =========================================================
# DATABASE
# =========================================================

def get_db():
    return psycopg2.connect(
        DATABASE_URL,
        connect_timeout=10
    )


def now():
    return datetime.now(timezone.utc)


def init_database():

    conn = get_db()

    try:
        with conn.cursor() as cursor:

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT DEFAULT '',
                    first_name TEXT DEFAULT '',
                    balance BIGINT NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id BIGSERIAL PRIMARY KEY,
                    txn_id TEXT UNIQUE NOT NULL,
                    user_id BIGINT NOT NULL,
                    txn_type TEXT NOT NULL,
                    amount BIGINT NOT NULL,
                    balance_after BIGINT NOT NULL,
                    product TEXT DEFAULT '',
                    note TEXT DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL
                )
            """)

        conn.commit()

    finally:
        conn.close()

    logger.info("PostgreSQL database initialized.")


# =========================================================
# USER MANAGEMENT
# =========================================================

def register_user(message):

    user = message.from_user

    conn = get_db()

    try:
        with conn.cursor() as cursor:

            cursor.execute("""
                INSERT INTO users (
                    user_id,
                    username,
                    first_name,
                    balance,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, 0, %s, %s)
                ON CONFLICT (user_id)
                DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    updated_at = EXCLUDED.updated_at
            """, (
                user.id,
                user.username or "",
                user.first_name or "",
                now(),
                now()
            ))

        conn.commit()

    finally:
        conn.close()


def ensure_user(user_id):

    conn = get_db()

    try:
        with conn.cursor() as cursor:

            cursor.execute("""
                INSERT INTO users (
                    user_id,
                    balance,
                    created_at,
                    updated_at
                )
                VALUES (%s, 0, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
            """, (
                user_id,
                now(),
                now()
            ))

        conn.commit()

    finally:
        conn.close()


def get_balance(user_id):

    ensure_user(user_id)

    conn = get_db()

    try:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cursor:

            cursor.execute("""
                SELECT balance
                FROM users
                WHERE user_id = %s
            """, (user_id,))

            row = cursor.fetchone()

            return int(row["balance"])

    finally:
        conn.close()


# =========================================================
# TRANSACTION ID
# =========================================================

def generate_txn_id():

    return "SF-" + secrets.token_hex(6).upper()


# =========================================================
# CREDIT BALANCE
# =========================================================

def credit_balance(
    user_id,
    amount,
    note="Admin credit"
):

    ensure_user(user_id)

    conn = get_db()

    try:
        # Transaction starts automatically.
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cursor:

            # Lock user's row.
            cursor.execute("""
                SELECT balance
                FROM users
                WHERE user_id = %s
                FOR UPDATE
            """, (user_id,))

            row = cursor.fetchone()

            if not row:
                raise ValueError("User not found.")

            old_balance = int(row["balance"])
            new_balance = old_balance + amount

            txn_id = generate_txn_id()

            cursor.execute("""
                UPDATE users
                SET balance = %s,
                    updated_at = %s
                WHERE user_id = %s
            """, (
                new_balance,
                now(),
                user_id
            ))

            cursor.execute("""
                INSERT INTO transactions (
                    txn_id,
                    user_id,
                    txn_type,
                    amount,
                    balance_after,
                    product,
                    note,
                    created_at
                )
                VALUES (
                    %s,
                    %s,
                    'CREDIT',
                    %s,
                    %s,
                    '',
                    %s,
                    %s
                )
            """, (
                txn_id,
                user_id,
                amount,
                new_balance,
                note,
                now()
            ))

        conn.commit()

        return txn_id, new_balance

    except Exception:

        conn.rollback()

        logger.exception(
            "Credit transaction failed."
        )

        raise

    finally:
        conn.close()


# =========================================================
# DEBIT BALANCE
# =========================================================

def debit_balance(
    user_id,
    amount,
    product_name
):

    ensure_user(user_id)

    conn = get_db()

    try:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cursor:

            cursor.execute("""
                SELECT balance
                FROM users
                WHERE user_id = %s
                FOR UPDATE
            """, (user_id,))

            row = cursor.fetchone()

            if not row:
                return False, 0, None

            current_balance = int(
                row["balance"]
            )

            if current_balance < amount:
                return False, current_balance, None

            new_balance = (
                current_balance - amount
            )

            txn_id = generate_txn_id()

            cursor.execute("""
                UPDATE users
                SET balance = %s,
                    updated_at = %s
                WHERE user_id = %s
            """, (
                new_balance,
                now(),
                user_id
            ))

            cursor.execute("""
                INSERT INTO transactions (
                    txn_id,
                    user_id,
                    txn_type,
                    amount,
                    balance_after,
                    product,
                    note,
                    created_at
                )
                VALUES (
                    %s,
                    %s,
                    'DEBIT',
                    %s,
                    %s,
                    %s,
                    'Product purchase',
                    %s
                )
            """, (
                txn_id,
                user_id,
                amount,
                new_balance,
                product_name,
                now()
            ))

        conn.commit()

        return True, new_balance, txn_id

    except Exception:

        conn.rollback()

        logger.exception(
            "Debit transaction failed."
        )

        return False, 0, None

    finally:
        conn.close()


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
def start(message):

    register_user(message)

    bot.send_message(
        message.chat.id,
        (
            "👋 *Welcome to SpeedFistt Store!*\n\n"
            "🛍️ Digital products खरीदने के लिए "
            "नीचे menu का इस्तेमाल करें।"
        ),
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


# =========================================================
# BALANCE
# =========================================================

@bot.message_handler(commands=["balance"])
def balance_command(message):

    register_user(message)

    balance = get_balance(
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


# =========================================================
# ADMIN ADD BALANCE
# =========================================================

@bot.message_handler(commands=["add"])
def admin_add(message):

    if message.from_user.id != ADMIN_ID:

        bot.send_message(
            message.chat.id,
            "❌ आपको इस command की permission नहीं है।"
        )

        return

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

    try:

        target_user = int(args[1])
        amount = int(args[2])

    except ValueError:

        bot.send_message(
            message.chat.id,
            "❌ User ID और Amount valid numbers होने चाहिए।"
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

    try:

        txn_id, new_balance = credit_balance(
            target_user,
            amount,
            f"Admin credit by {ADMIN_ID}"
        )

        bot.send_message(
            message.chat.id,
            (
                "✅ *Balance Added*\n\n"
                f"👤 User ID: `{target_user}`\n"
                f"💵 Added: *₹{amount}*\n"
                f"💰 New Balance: *₹{new_balance}*\n"
                f"🧾 Transaction: `{txn_id}`"
            ),
            parse_mode="Markdown"
        )

        try:

            bot.send_message(
                target_user,
                (
                    "🎉 *Balance Added!*\n\n"
                    f"💵 Added: *₹{amount}*\n"
                    f"💰 New Balance: *₹{new_balance}*\n"
                    f"🧾 Transaction: `{txn_id}`"
                ),
                parse_mode="Markdown"
            )

        except Exception as e:

            logger.warning(
                "User notification failed: %s",
                e
            )

    except Exception:

        bot.send_message(
            message.chat.id,
            "❌ Database error. Balance add नहीं हुआ।"
        )


# =========================================================
# ADMIN USERS
# =========================================================

@bot.message_handler(commands=["users"])
def users_command(message):

    if message.from_user.id != ADMIN_ID:
        return

    conn = get_db()

    try:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cursor:

            cursor.execute("""
                SELECT
                    user_id,
                    username,
                    first_name,
                    balance,
                    created_at
                FROM users
                ORDER BY created_at DESC
                LIMIT 50
            """)

            rows = cursor.fetchall()

    finally:
        conn.close()

    if not rows:

        bot.send_message(
            message.chat.id,
            "📭 अभी कोई users नहीं हैं।"
        )

        return

    text = "👥 *Recent Users*\n\n"

    for row in rows:

        username = (
            f"@{row['username']}"
            if row["username"]
            else "No username"
        )

        text += (
            f"👤 `{row['user_id']}`\n"
            f"Name: {row['first_name'] or '-'}\n"
            f"Username: {username}\n"
            f"Balance: ₹{row['balance']}\n\n"
        )

    bot.send_message(
        message.chat.id,
        text,
        parse_mode="Markdown"
    )


# =========================================================
# ADMIN HISTORY
# =========================================================

@bot.message_handler(commands=["history"])
def history_command(message):

    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split()

    if len(args) != 2:

        bot.send_message(
            message.chat.id,
            "`/history USER_ID`",
            parse_mode="Markdown"
        )

        return

    try:
        target_user = int(args[1])

    except ValueError:

        bot.send_message(
            message.chat.id,
            "❌ Invalid User ID."
        )

        return

    conn = get_db()

    try:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cursor:

            cursor.execute("""
                SELECT
                    txn_id,
                    txn_type,
                    amount,
                    balance_after,
                    product,
                    created_at
                FROM transactions
                WHERE user_id = %s
                ORDER BY id DESC
                LIMIT 20
            """, (
                target_user,
            ))

            rows = cursor.fetchall()

    finally:
        conn.close()

    if not rows:

        bot.send_message(
            message.chat.id,
            "📭 कोई transaction नहीं मिली।"
        )

        return

    text = (
        "📋 *Transaction History*\n"
        f"User: `{target_user}`\n\n"
    )

    for row in rows:

        if row["txn_type"] == "CREDIT":
            icon = "🟢"
            sign = "+"
        else:
            icon = "🔴"
            sign = "-"

        product = row["product"] or "-"

        text += (
            f"{icon} `{row['txn_id']}`\n"
            f"Type: {row['txn_type']}\n"
            f"Amount: {sign}₹{row['amount']}\n"
            f"Balance: ₹{row['balance_after']}\n"
            f"Product: {product}\n"
            f"Time: {row['created_at']}\n\n"
        )

    bot.send_message(
        message.chat.id,
        text,
        parse_mode="Markdown"
    )


# =========================================================
# ADMIN STATS
# =========================================================

@bot.message_handler(commands=["stats"])
def stats_command(message):

    if message.from_user.id != ADMIN_ID:
        return

    conn = get_db()

    try:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cursor:

            cursor.execute(
                "SELECT COUNT(*) AS total FROM users"
            )
            total_users = cursor.fetchone()["total"]

            cursor.execute("""
                SELECT COALESCE(SUM(balance), 0) AS total
                FROM users
            """)
            total_balance = cursor.fetchone()["total"]

            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) AS total
                FROM transactions
                WHERE txn_type = 'CREDIT'
            """)
            total_credited = cursor.fetchone()["total"]

            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) AS total
                FROM transactions
                WHERE txn_type = 'DEBIT'
            """)
            total_spent = cursor.fetchone()["total"]

            cursor.execute("""
                SELECT COUNT(*) AS total
                FROM transactions
                WHERE txn_type = 'DEBIT'
            """)
            total_purchases = cursor.fetchone()["total"]

    finally:
        conn.close()

    bot.send_message(
        message.chat.id,
        (
            "📊 *SpeedFistt Statistics*\n\n"
            f"👥 Users: *{total_users}*\n"
            f"💰 Current Balance: *₹{total_balance}*\n"
            f"🟢 Total Credits: *₹{total_credited}*\n"
            f"🔴 Total Spent: *₹{total_spent}*\n"
            f"🛒 Purchases: *{total_purchases}*"
        ),
        parse_mode="Markdown"
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
            "QR code sending failed."
        )

        bot.send_message(
            message.chat.id,
            caption,
            parse_mode="Markdown"
        )


# =========================================================
# PRODUCT PURCHASE
# =========================================================

def process_purchase(
    message,
    product_name,
    price,
    delivery_text
):

    user_id = message.from_user.id

    success, new_balance, txn_id = debit_balance(
        user_id,
        price,
        product_name
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

    bot.send_message(
        message.chat.id,
        (
            "✅ *Purchase Successful!*\n\n"
            f"📦 Product: *{product_name}*\n"
            f"💸 Paid: *₹{price}*\n"
            f"💰 Remaining: *₹{new_balance}*\n"
            f"🧾 Transaction: `{txn_id}`\n\n"
            f"{delivery_text}"
        ),
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


# =========================================================
# MAIN MESSAGE HANDLER
# =========================================================

@bot.message_handler(
    func=lambda message: True
)
def message_handler(message):

    register_user(message)

    text = message.text or ""

    if text == "BALANCE ✅":

        balance = get_balance(
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
            399,
            "📦 आपका digital product यहाँ उपलब्ध होगा।"
        )

    elif text == "🛒 PRODUCT 2 (₹599)":

        process_purchase(
            message,
            "SpeedFistt Product 2",
            599,
            "📦 आपका digital product यहाँ उपलब्ध होगा।"
        )

    elif text == "वापस जाएँ 🔙":

        bot.send_message(
            message.chat.id,
            "🔙 *Main Menu*",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )


# =========================================================
# RUN
# =========================================================

def main():

    init_database()

    logger.info(
        "SpeedFistt Store Bot started."
    )

    print(
        "🤖 SpeedFistt Store Bot is running..."
    )

    bot.infinity_polling(
        skip_pending=True
    )


if __name__ == "__main__":
    main()
```