import os
import sqlite3
import random
import base64
import threading
from datetime import datetime

import telebot
from telebot import types


# ============================================================
# AsklyBux Task Bot
# Python 3.11 + pyTelegramBotAPI + SQLite + Polling
# ============================================================

# Add token manually here or through Railway variable BOTTOKEN.
BOTTOKEN = ""

# Admin Telegram user ID.
ADMINID = 8907284640

# Optional: admin bot username for instruction text only.
ADMIN_BOT_USERNAME = os.getenv("ADMIN_BOT_USERNAME", "")

TOKEN = os.getenv("BOTTOKEN", BOTTOKEN)

if not TOKEN:
    raise ValueError("BOTTOKEN is empty. Add your bot token in main.py or Railway variables.")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

DB_NAME = "asklybux_userbot.db"
db_lock = threading.Lock()

# Temporary user states for multi-step flow.
user_states = {}


# ============================================================
# Database helpers
# ============================================================

def db_connect():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_lock:
        conn = db_connect()
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                userid INTEGER PRIMARY KEY,
                username TEXT,
                firstname TEXT,
                joined_at TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS wallet (
                userid INTEGER PRIMARY KEY,
                balance REAL DEFAULT 0.0
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                reward REAL NOT NULL,
                active INTEGER DEFAULT 1,
                created_at TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS taskstock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                firstname TEXT NOT NULL,
                login TEXT NOT NULL,
                password TEXT NOT NULL,
                email TEXT NOT NULL,
                assigned INTEGER DEFAULT 0,
                assigned_to INTEGER,
                assigned_at TEXT,
                created_at TEXT,
                FOREIGN KEY(task_id) REFERENCES tasks(id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS assignedtasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                userid INTEGER NOT NULL,
                task_id INTEGER NOT NULL,
                stock_id INTEGER NOT NULL,
                status TEXT DEFAULT 'assigned',
                twofa TEXT,
                decoded_twofa TEXT,
                assigned_at TEXT,
                submitted_at TEXT,
                UNIQUE(stock_id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS pendingaccounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                userid INTEGER NOT NULL,
                task_id INTEGER NOT NULL,
                stock_id INTEGER NOT NULL,
                task_name TEXT NOT NULL,
                reward REAL NOT NULL,
                firstname TEXT NOT NULL,
                login TEXT NOT NULL,
                password TEXT NOT NULL,
                email TEXT NOT NULL,
                twofa TEXT,
                decoded_twofa TEXT,
                status TEXT DEFAULT 'pending',
                submitted_at TEXT
            )
        """)

        # Add a starter example task only if no tasks exist.
        cur.execute("SELECT COUNT(*) AS total FROM tasks")
        total_tasks = cur.fetchone()["total"]

        if total_tasks == 0:
            cur.execute("""
                INSERT INTO tasks (name, reward, active, created_at)
                VALUES (?, ?, 1, ?)
            """, ("📱 Create Inst (2FA)", 0.0200, now()))

        conn.commit()
        conn.close()


def now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def register_user(message):
    userid = message.from_user.id
    username = message.from_user.username or ""
    firstname = message.from_user.first_name or ""

    with db_lock:
        conn = db_connect()
        cur = conn.cursor()

        cur.execute("""
            INSERT OR IGNORE INTO users (userid, username, firstname, joined_at)
            VALUES (?, ?, ?, ?)
        """, (userid, username, firstname, now()))

        cur.execute("""
            UPDATE users SET username = ?, firstname = ?
            WHERE userid = ?
        """, (username, firstname, userid))

        cur.execute("""
            INSERT OR IGNORE INTO wallet (userid, balance)
            VALUES (?, 0.0)
        """, (userid,))

        conn.commit()
        conn.close()


def get_balance(userid):
    with db_lock:
        conn = db_connect()
        cur = conn.cursor()

        cur.execute("INSERT OR IGNORE INTO wallet (userid, balance) VALUES (?, 0.0)", (userid,))
        cur.execute("SELECT balance FROM wallet WHERE userid = ?", (userid,))
        row = cur.fetchone()

        conn.commit()
        conn.close()

    return float(row["balance"]) if row else 0.0


def add_balance(userid, amount):
    with db_lock:
        conn = db_connect()
        cur = conn.cursor()

        cur.execute("INSERT OR IGNORE INTO wallet (userid, balance) VALUES (?, 0.0)", (userid,))
        cur.execute("UPDATE wallet SET balance = balance + ? WHERE userid = ?", (amount, userid))

        conn.commit()
        conn.close()


def remove_balance(userid, amount):
    with db_lock:
        conn = db_connect()
        cur = conn.cursor()

        cur.execute("INSERT OR IGNORE INTO wallet (userid, balance) VALUES (?, 0.0)", (userid,))
        cur.execute("""
            UPDATE wallet
            SET balance = CASE
                WHEN balance - ? < 0 THEN 0
                ELSE balance - ?
            END
            WHERE userid = ?
        """, (amount, amount, userid))

        conn.commit()
        conn.close()


def get_active_tasks():
    with db_lock:
        conn = db_connect()
        cur = conn.cursor()

        cur.execute("""
            SELECT t.*,
                   COUNT(s.id) AS stock_count
            FROM tasks t
            LEFT JOIN taskstock s ON s.task_id = t.id AND s.assigned = 0
            WHERE t.active = 1
            GROUP BY t.id
            ORDER BY t.id DESC
        """)
        rows = cur.fetchall()

        conn.close()

    return rows


def get_task(task_id):
    with db_lock:
        conn = db_connect()
        cur = conn.cursor()

        cur.execute("SELECT * FROM tasks WHERE id = ? AND active = 1", (task_id,))
        row = cur.fetchone()

        conn.close()

    return row


def assign_random_stock(userid, task_id):
    """
    Important lock system:
    - Select one unassigned stock item.
    - Mark it assigned immediately.
    - Save assignment persistently.
    - UNIQUE(stock_id) prevents duplication.
    """
    with db_lock:
        conn = db_connect()
        cur = conn.cursor()

        try:
            cur.execute("BEGIN IMMEDIATE")

            cur.execute("""
                SELECT * FROM taskstock
                WHERE task_id = ? AND assigned = 0
                ORDER BY RANDOM()
                LIMIT 1
            """, (task_id,))
            stock = cur.fetchone()

            if not stock:
                conn.rollback()
                conn.close()
                return None

            cur.execute("""
                UPDATE taskstock
                SET assigned = 1, assigned_to = ?, assigned_at = ?
                WHERE id = ? AND assigned = 0
            """, (userid, now(), stock["id"]))

            if cur.rowcount == 0:
                conn.rollback()
                conn.close()
                return None

            cur.execute("""
                INSERT INTO assignedtasks
                (userid, task_id, stock_id, status, assigned_at)
                VALUES (?, ?, ?, 'assigned', ?)
            """, (userid, task_id, stock["id"], now()))

            conn.commit()

            cur.execute("""
                SELECT s.*, t.name AS task_name, t.reward AS reward
                FROM taskstock s
                JOIN tasks t ON t.id = s.task_id
                WHERE s.id = ?
            """, (stock["id"],))
            assigned = cur.fetchone()

            conn.close()
            return assigned

        except sqlite3.IntegrityError:
            conn.rollback()
            conn.close()
            return None
        except Exception:
            conn.rollback()
            conn.close()
            raise


def get_assigned_by_user(userid, stock_id):
    with db_lock:
        conn = db_connect()
        cur = conn.cursor()

        cur.execute("""
            SELECT a.*, s.firstname, s.login, s.password, s.email,
                   t.name AS task_name, t.reward AS reward
            FROM assignedtasks a
            JOIN taskstock s ON s.id = a.stock_id
            JOIN tasks t ON t.id = a.task_id
            WHERE a.userid = ? AND a.stock_id = ?
        """, (userid, stock_id))
        row = cur.fetchone()

        conn.close()

    return row


def cancel_assignment(userid, stock_id):
    """
    Cancel returns stock back to available pool only if not submitted.
    """
    with db_lock:
        conn = db_connect()
        cur = conn.cursor()

        cur.execute("""
            SELECT * FROM assignedtasks
            WHERE userid = ? AND stock_id = ? AND status = 'assigned'
        """, (userid, stock_id))
        assignment = cur.fetchone()

        if not assignment:
            conn.close()
            return False

        cur.execute("""
            UPDATE taskstock
            SET assigned = 0, assigned_to = NULL, assigned_at = NULL
            WHERE id = ?
        """, (stock_id,))

        cur.execute("""
            UPDATE assignedtasks
            SET status = 'cancelled'
            WHERE userid = ? AND stock_id = ?
        """, (userid, stock_id))

        conn.commit()
        conn.close()

    return True


def save_pending_submission(userid, stock_id, twofa, decoded_twofa):
    with db_lock:
        conn = db_connect()
        cur = conn.cursor()

        cur.execute("""
            SELECT a.*, s.firstname, s.login, s.password, s.email,
                   t.name AS task_name, t.reward AS reward
            FROM assignedtasks a
            JOIN taskstock s ON s.id = a.stock_id
            JOIN tasks t ON t.id = a.task_id
            WHERE a.userid = ? AND a.stock_id = ? AND a.status = 'assigned'
        """, (userid, stock_id))
        row = cur.fetchone()

        if not row:
            conn.close()
            return None

        cur.execute("""
            INSERT INTO pendingaccounts
            (userid, task_id, stock_id, task_name, reward, firstname, login,
             password, email, twofa, decoded_twofa, status, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """, (
            userid,
            row["task_id"],
            stock_id,
            row["task_name"],
            float(row["reward"]),
            row["firstname"],
            row["login"],
            row["password"],
            row["email"],
            twofa,
            decoded_twofa,
            now()
        ))

        pending_id = cur.lastrowid

        cur.execute("""
            UPDATE assignedtasks
            SET status = 'pending',
                twofa = ?,
                decoded_twofa = ?,
                submitted_at = ?
            WHERE userid = ? AND stock_id = ?
        """, (twofa, decoded_twofa, now(), userid, stock_id))

        conn.commit()

        cur.execute("SELECT * FROM pendingaccounts WHERE id = ?", (pending_id,))
        pending = cur.fetchone()

        conn.close()

    return pending


def mark_pending_status(userid, status):
    with db_lock:
        conn = db_connect()
        cur = conn.cursor()

        cur.execute("""
            SELECT * FROM pendingaccounts
            WHERE userid = ? AND status = 'pending'
            ORDER BY id DESC
            LIMIT 1
        """, (userid,))
        row = cur.fetchone()

        if not row:
            conn.close()
            return None

        cur.execute("""
            UPDATE pendingaccounts
            SET status = ?
            WHERE id = ?
        """, (status, row["id"]))

        cur.execute("""
            UPDATE assignedtasks
            SET status = ?
            WHERE userid = ? AND stock_id = ?
        """, (status, userid, row["stock_id"]))

        conn.commit()
        conn.close()

    return row


# ============================================================
# UI helpers
# ============================================================

def main_menu_markup():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📋 Tasks", callback_data="tasks"),
        types.InlineKeyboardButton("💰 Balance", callback_data="balance")
    )
    return markup


def back_menu_markup():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="home"))
    return markup


def tasks_markup():
    markup = types.InlineKeyboardMarkup(row_width=1)
    tasks = get_active_tasks()

    for task in tasks:
        reward = float(task["reward"])
        stock_count = int(task["stock_count"])
        text = f'{task["name"]} (${reward:.4f})'

        if stock_count <= 0:
            text += " — Out of stock"

        markup.add(types.InlineKeyboardButton(text, callback_data=f"task_{task['id']}"))

    markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="home"))
    return markup


def assigned_task_markup(stock_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("📨 Get Code", callback_data=f"getcode_{stock_id}"))
    markup.add(types.InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{stock_id}"))
    return markup


def submit_markup(stock_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("✅ Submit Account", callback_data=f"submit_{stock_id}"))
    markup.add(types.InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{stock_id}"))
    return markup


def safe_edit(call, text, markup=None):
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup)


# ============================================================
# 2FA decoder
# ============================================================

def decode_2fa_key(secret):
    """
    Base32 decode only using Python builtin base64.
    Returns decoded text if valid UTF-8, otherwise hex string.
    """
    cleaned = secret.strip().replace(" ", "").upper()

    missing_padding = len(cleaned) % 8
    if missing_padding:
        cleaned += "=" * (8 - missing_padding)

    decoded_bytes = base64.b32decode(cleaned, casefold=True)

    try:
        return decoded_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return decoded_bytes.hex()


# ============================================================
# Bot handlers
# ============================================================

@bot.message_handler(commands=["start"])
def start_handler(message):
    register_user(message)

    text = (
        "👋 <b>Welcome to AsklyBux!</b>\n\n"
        "💸 Earn money by completing simple tasks.\n\n"
        "By using this bot, you agree to Terms & Privacy Policy."
    )

    bot.send_message(message.chat.id, text, reply_markup=main_menu_markup())


@bot.callback_query_handler(func=lambda call: call.data == "home")
def home_callback(call):
    register_user(call.message)

    text = (
        "👋 <b>Welcome to AsklyBux!</b>\n\n"
        "💸 Earn money by completing simple tasks.\n\n"
        "By using this bot, you agree to Terms & Privacy Policy."
    )

    safe_edit(call, text, main_menu_markup())
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "balance")
def balance_callback(call):
    userid = call.from_user.id
    balance = get_balance(userid)

    text = (
        "💰 <b>Wallet Balance</b>\n\n"
        f"${balance:.4f}"
    )

    safe_edit(call, text, back_menu_markup())
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "tasks")
def tasks_callback(call):
    text = (
        "📋 <b>Available Tasks</b>\n\n"
        "Choose a task below."
    )

    safe_edit(call, text, tasks_markup())
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("task_"))
def select_task_callback(call):
    userid = call.from_user.id

    try:
        task_id = int(call.data.split("_")[1])
    except Exception:
        bot.answer_callback_query(call.id, "Invalid task.")
        return

    task = get_task(task_id)
    if not task:
        bot.answer_callback_query(call.id, "Task not found.")
        return

    assigned = assign_random_stock(userid, task_id)
    if not assigned:
        bot.answer_callback_query(call.id, "No stock available.")
        safe_edit(
            call,
            "📦 <b>Out of Stock</b>\n\nThis task has no available accounts right now.",
            tasks_markup()
        )
        return

    text = (
        "📋 <b>Task Details</b>\n\n"
        f"👤 <b>First Name:</b> <code>{assigned['firstname']}</code>\n"
        f"🔑 <b>Login:</b> <code>{assigned['login']}</code>\n"
        f"🔒 <b>Password:</b> <code>{assigned['password']}</code>\n"
        f"📧 <b>Email:</b> <code>{assigned['email']}</code>"
    )

    safe_edit(call, text, assigned_task_markup(assigned["id"]))
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("getcode_"))
def get_code_callback(call):
    userid = call.from_user.id

    try:
        stock_id = int(call.data.split("_")[1])
    except Exception:
        bot.answer_callback_query(call.id, "Invalid request.")
        return

    assigned = get_assigned_by_user(userid, stock_id)

    if not assigned or assigned["status"] != "assigned":
        bot.answer_callback_query(call.id, "Task not active.")
        return

    admin_text = (
        "📨 <b>New Code Request</b>\n\n"
        f"📧 <b>Email:</b> <code>{assigned['email']}</code>\n"
        f"👤 <b>Username:</b> <code>{assigned['login']}</code>\n"
        f"🆔 <b>UserID:</b> <code>{userid}</code>\n\n"
        f"Admin command:\n<code>/code {userid} CODE</code>"
    )

    try:
        bot.send_message(ADMINID, admin_text)
    except Exception:
        pass

    text = (
        "📨 <b>Code request sent.</b>\n\n"
        "Please wait for admin to send your verification code."
    )

    bot.send_message(call.message.chat.id, text)
    bot.answer_callback_query(call.id, "Request sent.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("cancel_"))
def cancel_callback(call):
    userid = call.from_user.id

    try:
        stock_id = int(call.data.split("_")[1])
    except Exception:
        bot.answer_callback_query(call.id, "Invalid request.")
        return

    success = cancel_assignment(userid, stock_id)

    if success:
        text = "❌ <b>Task cancelled.</b>\n\nThe account was returned to available stock."
    else:
        text = "⚠️ This task cannot be cancelled now."

    safe_edit(call, text, main_menu_markup())
    bot.answer_callback_query(call.id)


@bot.message_handler(commands=["code"])
def user_receive_code_command(message):
    """
    This command is useful if admin sends /code directly to this user bot.
    Format:
    /code userid code
    """
    if message.from_user.id != ADMINID:
        bot.reply_to(message, "🚫 Access denied.")
        return

    parts = message.text.split(maxsplit=2)

    if len(parts) < 3:
        bot.reply_to(message, "Usage: /code userid code")
        return

    try:
        userid = int(parts[1])
        code = parts[2].strip()
    except Exception:
        bot.reply_to(message, "Invalid format.")
        return

    text = (
        "📩 <b>Verification Code:</b>\n\n"
        f"<code>{code}</code>\n\n"
        "🔐 Send your 2FA key."
    )

    try:
        bot.send_message(userid, text)
        user_states[userid] = {
            "step": "waiting_2fa"
        }
        bot.reply_to(message, "✅ Code forwarded.")
    except Exception:
        bot.reply_to(message, "❌ Could not send code to user.")


@bot.message_handler(commands=["add"])
def admin_add_balance_command(message):
    if message.from_user.id != ADMINID:
        bot.reply_to(message, "🚫 Access denied.")
        return

    parts = message.text.split(maxsplit=2)

    if len(parts) < 3:
        bot.reply_to(message, "Usage: /add userid amount")
        return

    try:
        userid = int(parts[1])
        amount = float(parts[2])
    except Exception:
        bot.reply_to(message, "Invalid format.")
        return

    add_balance(userid, amount)

    try:
        bot.send_message(userid, f"🎉 <b>Approved</b>\n\n+${amount:.4f} added.")
    except Exception:
        pass

    mark_pending_status(userid, "approved")

    bot.reply_to(message, f"✅ Added ${amount:.4f} to {userid}.")


@bot.message_handler(commands=["remove"])
def admin_remove_balance_command(message):
    if message.from_user.id != ADMINID:
        bot.reply_to(message, "🚫 Access denied.")
        return

    parts = message.text.split(maxsplit=2)

    if len(parts) < 3:
        bot.reply_to(message, "Usage: /remove userid amount")
        return

    try:
        userid = int(parts[1])
        amount = float(parts[2])
    except Exception:
        bot.reply_to(message, "Invalid format.")
        return

    remove_balance(userid, amount)

    try:
        bot.send_message(userid, f"💸 <b>Wallet Updated</b>\n\n-${amount:.4f} removed.")
    except Exception:
        pass

    bot.reply_to(message, f"✅ Removed ${amount:.4f} from {userid}.")


@bot.message_handler(commands=["reject"])
def admin_reject_command(message):
    """
    Optional helper if admin wants to reject through user bot:
    /reject userid
    """
    if message.from_user.id != ADMINID:
        bot.reply_to(message, "🚫 Access denied.")
        return

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        bot.reply_to(message, "Usage: /reject userid")
        return

    try:
        userid = int(parts[1])
    except Exception:
        bot.reply_to(message, "Invalid userid.")
        return

    mark_pending_status(userid, "rejected")

    try:
        bot.send_message(userid, "❌ <b>Rejected.</b>")
    except Exception:
        pass

    bot.reply_to(message, f"✅ Rejected latest pending submission from {userid}.")


@bot.message_handler(func=lambda message: True, content_types=["text"])
def text_handler(message):
    userid = message.from_user.id
    state = user_states.get(userid)

    if not state:
        bot.send_message(
            message.chat.id,
            "Please use the menu below.",
            reply_markup=main_menu_markup()
        )
        return

    if state.get("step") == "waiting_2fa":
        twofa = message.text.strip()

        try:
            decoded = decode_2fa_key(twofa)
        except Exception:
            bot.send_message(
                message.chat.id,
                "❌ Invalid Base32 2FA key. Please send a valid key."
            )
            return

        user_states[userid] = {
            "step": "decoded_2fa",
            "twofa": twofa,
            "decoded": decoded
        }

        # Find latest active assigned task.
        with db_lock:
            conn = db_connect()
            cur = conn.cursor()

            cur.execute("""
                SELECT stock_id FROM assignedtasks
                WHERE userid = ? AND status = 'assigned'
                ORDER BY id DESC
                LIMIT 1
            """, (userid,))
            row = cur.fetchone()

            conn.close()

        if not row:
            bot.send_message(
                message.chat.id,
                "⚠️ No active task found.",
                reply_markup=main_menu_markup()
            )
            user_states.pop(userid, None)
            return

        stock_id = row["stock_id"]

        text = (
            "✅ <b>Decoded 2FA</b>\n\n"
            f"<code>{decoded}</code>"
        )

        bot.send_message(message.chat.id, text, reply_markup=submit_markup(stock_id))
        return


@bot.callback_query_handler(func=lambda call: call.data.startswith("submit_"))
def submit_callback(call):
    userid = call.from_user.id

    try:
        stock_id = int(call.data.split("_")[1])
    except Exception:
        bot.answer_callback_query(call.id, "Invalid request.")
        return

    state = user_states.get(userid)

    if not state or state.get("step") != "decoded_2fa":
        bot.answer_callback_query(call.id, "Send 2FA key first.")
        return

    pending = save_pending_submission(
        userid=userid,
        stock_id=stock_id,
        twofa=state["twofa"],
        decoded_twofa=state["decoded"]
    )

    if not pending:
        bot.answer_callback_query(call.id, "Could not submit.")
        return

    admin_text = (
        "🛑 <b>New Pending Account</b>\n\n"
        f"📋 <b>Task:</b> {pending['task_name']}\n"
        f"💰 <b>Reward:</b> ${float(pending['reward']):.4f}\n\n"
        f"👤 <b>First name:</b> <code>{pending['firstname']}</code>\n"
        f"🔑 <b>Login:</b> <code>{pending['login']}</code>\n"
        f"🔒 <b>Password:</b> <code>{pending['password']}</code>\n"
        f"📧 <b>Email:</b> <code>{pending['email']}</code>\n"
        f"🔐 <b>2FA:</b> <code>{pending['twofa']}</code>\n"
        f"✅ <b>Decoded:</b> <code>{pending['decoded_twofa']}</code>\n"
        f"🆔 <b>UserID:</b> <code>{pending['userid']}</code>\n\n"
        "Status: <b>Pending</b>\n\n"
        f"Approve:\n<code>/add {pending['userid']} {float(pending['reward']):.4f}</code>\n"
        f"Reject:\n<code>/reject {pending['userid']}</code>"
    )

    try:
        bot.send_message(ADMINID, admin_text)
    except Exception:
        pass

    user_states.pop(userid, None)

    text = (
        "⏳ <b>Submitted successfully.</b>\n\n"
        "Waiting for admin review."
    )

    safe_edit(call, text, main_menu_markup())
    bot.answer_callback_query(call.id, "Submitted.")


# ============================================================
# Admin helper commands for adding tasks/stock directly in user bot
# These are optional but useful because this bot owns the user database.
# ============================================================

@bot.message_handler(commands=["newtask"])
def newtask_command(message):
    """
    /newtask Task Name | 0.0200
    """
    if message.from_user.id != ADMINID:
        bot.reply_to(message, "🚫 Access denied.")
        return

    payload = message.text.replace("/newtask", "", 1).strip()

    if "|" not in payload:
        bot.reply_to(message, "Usage: /newtask Task Name | 0.0200")
        return

    name, reward_text = payload.split("|", 1)

    try:
        reward = float(reward_text.strip())
    except Exception:
        bot.reply_to(message, "Invalid reward.")
        return

    with db_lock:
        conn = db_connect()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO tasks (name, reward, active, created_at)
            VALUES (?, ?, 1, ?)
        """, (name.strip(), reward, now()))

        conn.commit()
        conn.close()

    bot.reply_to(message, "✅ Task created.")


@bot.message_handler(commands=["addstock"])
def addstock_command(message):
    """
    /addstock task_id | firstname | login | password | email
    """
    if message.from_user.id != ADMINID:
        bot.reply_to(message, "🚫 Access denied.")
        return

    payload = message.text.replace("/addstock", "", 1).strip()
    parts = [p.strip() for p in payload.split("|")]

    if len(parts) != 5:
        bot.reply_to(message, "Usage: /addstock task_id | firstname | login | password | email")
        return

    try:
        task_id = int(parts[0])
    except Exception:
        bot.reply_to(message, "Invalid task_id.")
        return

    task = get_task(task_id)
    if not task:
        bot.reply_to(message, "Task not found.")
        return

    with db_lock:
        conn = db_connect()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO taskstock
            (task_id, firstname, login, password, email, assigned, created_at)
            VALUES (?, ?, ?, ?, ?, 0, ?)
        """, (task_id, parts[1], parts[2], parts[3], parts[4], now()))

        conn.commit()
        conn.close()

    bot.reply_to(message, "✅ Stock added.")


@bot.message_handler(commands=["taskslist"])
def taskslist_command(message):
    if message.from_user.id != ADMINID:
        bot.reply_to(message, "🚫 Access denied.")
        return

    tasks = get_active_tasks()

    if not tasks:
        bot.reply_to(message, "No tasks found.")
        return

    lines = ["📋 <b>Tasks</b>\n"]

    for task in tasks:
        lines.append(
            f"ID: <code>{task['id']}</code> | {task['name']} | "
            f"${float(task['reward']):.4f} | Stock: {task['stock_count']}"
        )

    bot.reply_to(message, "\n".join(lines))


# ============================================================
# Run bot
# ============================================================

if __name__ == "__main__":
    init_db()
    print("AsklyBux Task Bot is running with polling...")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
