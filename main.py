import os
import json
import logging
import firebase_admin
from firebase_admin import credentials, db
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    CallbackQueryHandler, filters, ContextTypes
)

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# ENV VARIABLES (Railway Variables থেকে নেওয়া হবে)
# ─────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")
FIREBASE_DATABASE_URL = os.environ.get("FIREBASE_DATABASE_URL")  # e.g. https://your-project-default-rtdb.firebaseio.com
FIREBASE_CREDENTIALS_JSON = os.environ.get("FIREBASE_CREDENTIALS_JSON")  # JSON string
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))  # তোমার নিজের chat_id

# ─────────────────────────────────────────────
# FIREBASE INIT
# ─────────────────────────────────────────────
cred_dict = json.loads(FIREBASE_CREDENTIALS_JSON)
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DATABASE_URL})

# ─────────────────────────────────────────────
# CONVERSATION STATES
# ─────────────────────────────────────────────
(
    MAIN_MENU,
    SIGNUP_USERNAME, SIGNUP_PASSWORD,
    LOGIN_USERNAME, LOGIN_PASSWORD,
    SAVE_ACC_NAME, SAVE_ACC_USERNAME, SAVE_ACC_PASSWORD, SAVE_ACC_2FA,
    VERIFY_PASSWORD,
) = range(10)

# ─────────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────────
def get_start_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 𝙎𝙞𝙜𝙣 𝙐𝙥", callback_data="signup")],
        [InlineKeyboardButton("🎉 𝙇𝙤𝙜𝙞𝙣", callback_data="login")],
    ])

def get_home_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📑 𝙎𝙖𝙫𝙚 𝘼𝙘𝙘𝙤𝙪𝙣𝙩")],
            [KeyboardButton("💝 𝙔𝙤𝙪𝙧 𝘼𝙘𝙘𝙤𝙪𝙣𝙩'𝙨")],
        ],
        resize_keyboard=True
    )

# ─────────────────────────────────────────────
# FIREBASE HELPERS
# ─────────────────────────────────────────────
def fb_get(path):
    try:
        return db.reference(path).get()
    except Exception:
        return None

def fb_set(path, data):
    db.reference(path).set(data)

def fb_delete(path):
    db.reference(path).delete()

def get_user_by_username(username):
    users = fb_get("users") or {}
    for uid, udata in users.items():
        if udata.get("username", "").lower() == username.lower():
            return uid, udata
    return None, None

def get_user_by_chat_id(chat_id):
    return fb_get(f"users/{chat_id}")

def is_logged_in(chat_id):
    udata = get_user_by_chat_id(chat_id)
    return udata is not None and udata.get("logged_in", False)

# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = user.id

    # Admin কে নতুন user এর info পাঠাও
    if ADMIN_CHAT_ID:
        admin_msg = (
            f"🔔 *New /start triggered!*\n\n"
            f"👤 Full Name: {user.full_name}\n"
            f"🆔 Username: @{user.username or 'N/A'}\n"
            f"💬 Chat ID: `{chat_id}`"
        )
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_msg,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Admin notify failed: {e}")

    # Already logged in?
    if is_logged_in(chat_id):
        await update.message.reply_text(
            f"👋 Welcome back, *{user.first_name}*!\nYou are already logged in.",
            parse_mode="Markdown",
            reply_markup=get_home_keyboard()
        )
        return MAIN_MENU

    await update.message.reply_text(
        f"👋 *Welcome to Account Saver Bot!*\n\n"
        f"Securely save and manage your accounts.\n\n"
        f"Please *Sign Up* or *Login* to continue:",
        parse_mode="Markdown",
        reply_markup=get_start_keyboard()
    )
    return MAIN_MENU

# ─────────────────────────────────────────────
# SIGN UP FLOW
# ─────────────────────────────────────────────
async def signup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📋 *Sign Up*\n\nPlease enter a *username* for your account:", parse_mode="Markdown")
    return SIGNUP_USERNAME

async def signup_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    if " " in username:
        await update.message.reply_text("❌ Username cannot contain spaces. Try again:")
        return SIGNUP_USERNAME

    # Check if username already taken
    uid, _ = get_user_by_username(username)
    if uid is not None:
        await update.message.reply_text("❌ Username already taken. Choose another:")
        return SIGNUP_USERNAME

    context.user_data["signup_username"] = username
    await update.message.reply_text(f"✅ Username: *{username}*\n\nNow enter a *password*:", parse_mode="Markdown")
    return SIGNUP_PASSWORD

async def signup_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    chat_id = update.effective_user.id
    user = update.effective_user
    username = context.user_data["signup_username"]

    # Save to Firebase
    fb_set(f"users/{chat_id}", {
        "username": username,
        "password": password,
        "full_name": user.full_name,
        "tg_username": user.username or "",
        "logged_in": True,
        "accounts": {}
    })

    await update.message.reply_text(
        f"🎉 *Account Created Successfully!*\n\n"
        f"Welcome, *{username}*!\nYou are now logged in.",
        parse_mode="Markdown",
        reply_markup=get_home_keyboard()
    )
    return MAIN_MENU

# ─────────────────────────────────────────────
# LOGIN FLOW
# ─────────────────────────────────────────────
async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🎉 *Login*\n\nEnter your *username*:", parse_mode="Markdown")
    return LOGIN_USERNAME

async def login_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    uid, udata = get_user_by_username(username)
    if uid is None:
        await update.message.reply_text("❌ Username not found. Try again:")
        return LOGIN_USERNAME

    context.user_data["login_uid"] = uid
    context.user_data["login_udata"] = udata
    await update.message.reply_text("🔑 Enter your *password*:", parse_mode="Markdown")
    return LOGIN_PASSWORD

async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    chat_id = update.effective_user.id
    uid = context.user_data["login_uid"]
    udata = context.user_data["login_udata"]

    if udata.get("password") != password:
        await update.message.reply_text("❌ Wrong password! Try again with /start")
        return ConversationHandler.END

    # If logging in from a different device/chat_id, update reference
    if str(uid) != str(chat_id):
        await update.message.reply_text("⚠️ This account is registered to a different Telegram account.")
        return ConversationHandler.END

    fb_set(f"users/{chat_id}/logged_in", True)

    await update.message.reply_text(
        f"✅ *Logged in successfully!*\n\nWelcome back, *{udata.get('username')}*!",
        parse_mode="Markdown",
        reply_markup=get_home_keyboard()
    )
    return MAIN_MENU

# ─────────────────────────────────────────────
# MAIN MENU HANDLER (Reply Keyboard)
# ─────────────────────────────────────────────
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_user.id

    if not is_logged_in(chat_id):
        await update.message.reply_text("Please /start first.")
        return MAIN_MENU

    if text == "📑 𝙎𝙖𝙫𝙚 𝘼𝙘𝙘𝙤𝙪𝙣𝙩":
        await update.message.reply_text(
            "💾 *Save Account*\n\nEnter a *name* for this account (e.g. Gmail, Facebook):",
            parse_mode="Markdown"
        )
        return SAVE_ACC_NAME

    elif text == "💝 𝙔𝙤𝙪𝙧 𝘼𝙘𝙘𝙤𝙪𝙣𝙩'𝙨":
        return await show_accounts(update, context)

    return MAIN_MENU

# ─────────────────────────────────────────────
# SAVE ACCOUNT FLOW
# ─────────────────────────────────────────────
async def save_acc_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_user.id
    name = update.message.text.strip()

    if "/" in name or " " in name:
        await update.message.reply_text("❌ Account name cannot have spaces or '/'. Try again:")
        return SAVE_ACC_NAME

    # Check duplicate
    existing = fb_get(f"users/{chat_id}/accounts/{name}")
    if existing:
        await update.message.reply_text(f"❌ An account named *{name}* already exists. Use a different name:", parse_mode="Markdown")
        return SAVE_ACC_NAME

    context.user_data["save_acc_name"] = name
    await update.message.reply_text(f"✅ Name: *{name}*\n\nEnter the *username* for this account:", parse_mode="Markdown")
    return SAVE_ACC_USERNAME

async def save_acc_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["save_acc_user"] = update.message.text.strip()
    await update.message.reply_text("🔑 Enter the *password* for this account:", parse_mode="Markdown")
    return SAVE_ACC_PASSWORD

async def save_acc_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["save_acc_pass"] = update.message.text.strip()
    await update.message.reply_text(
        "🔐 Enter the *2FA key* for this account.\n\n"
        "If no 2FA, type `none`:",
        parse_mode="Markdown"
    )
    return SAVE_ACC_2FA

async def save_acc_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_user.id
    twofa = update.message.text.strip()
    if twofa.lower() == "none":
        twofa = None

    name = context.user_data["save_acc_name"]
    acc_user = context.user_data["save_acc_user"]
    acc_pass = context.user_data["save_acc_pass"]

    acc_data = {
        "username": acc_user,
        "password": acc_pass,
    }
    if twofa:
        acc_data["2fa"] = twofa

    fb_set(f"users/{chat_id}/accounts/{name}", acc_data)

    await update.message.reply_text(
        f"✅ *Account saved!*\n\n"
        f"Use `/account {name}` to view it.",
        parse_mode="Markdown",
        reply_markup=get_home_keyboard()
    )
    return MAIN_MENU

# ─────────────────────────────────────────────
# SHOW ALL ACCOUNTS
# ─────────────────────────────────────────────
async def show_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_user.id
    accounts = fb_get(f"users/{chat_id}/accounts") or {}

    if not accounts:
        await update.message.reply_text("📭 You have no saved accounts yet.\n\nUse *📑 Save Account* to add one.", parse_mode="Markdown")
        return MAIN_MENU

    msg = "💝 *Your Saved Accounts:*\n\n"
    for name in accounts:
        msg += f"• `/account {name}`\n"
    msg += "\n_Tap a command to view account details._\n"
    msg += "_Use_ `/remove <name>` _to delete an account._"

    await update.message.reply_text(msg, parse_mode="Markdown")
    return MAIN_MENU

# ─────────────────────────────────────────────
# /account <name> COMMAND — with security check
# ─────────────────────────────────────────────
async def view_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text("Usage: `/account <account_name>`", parse_mode="Markdown")
        return MAIN_MENU

    name = context.args[0].strip()

    # Fetch the owner of this name from ALL users (security: name is unique per bot-account, not global)
    udata = get_user_by_chat_id(chat_id)
    if not udata:
        await update.message.reply_text("Please /start and login first.")
        return MAIN_MENU

    accounts = udata.get("accounts", {})

    if name not in accounts:
        # Check if someone else has this account name — security flow
        # We check every user for this account name
        all_users = fb_get("users") or {}
        found_owner = None
        for uid, ud in all_users.items():
            if str(uid) == str(chat_id):
                continue
            if name in (ud.get("accounts") or {}):
                found_owner = ud
                break

        if found_owner:
            # Someone is trying to access another user's account — demand password
            context.user_data["security_check_name"] = name
            context.user_data["security_check_owner_uid"] = None
            for uid, ud in all_users.items():
                if name in (ud.get("accounts") or {}):
                    context.user_data["security_check_owner_uid"] = uid
                    break
            await update.message.reply_text(
                "🔒 *Security Check!*\n\nThis account belongs to another user.\n"
                "Enter the *owner's bot password* to proceed:",
                parse_mode="Markdown"
            )
            return VERIFY_PASSWORD
        else:
            await update.message.reply_text(f"❌ No account named *{name}* found.", parse_mode="Markdown")
            return MAIN_MENU

    # Owner is accessing their own account
    acc = accounts[name]
    msg = (
        f"📋 *Account:* `{name}`\n\n"
        f"👤 Username: `{acc.get('username', 'N/A')}`\n"
        f"🔑 Password: `{acc.get('password', 'N/A')}`\n"
    )
    if acc.get("2fa"):
        msg += f"🔐 2FA Key: `{acc.get('2fa')}`\n"
    else:
        msg += "🔐 2FA: Not set\n"

    await update.message.reply_text(msg, parse_mode="Markdown")
    return MAIN_MENU

# ─────────────────────────────────────────────
# SECURITY VERIFY STATE
# ─────────────────────────────────────────────
async def verify_password_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    entered = update.message.text.strip()
    owner_uid = context.user_data.get("security_check_owner_uid")
    name = context.user_data.get("security_check_name")

    if not owner_uid:
        await update.message.reply_text("Something went wrong. Use /start.")
        return ConversationHandler.END

    owner_data = fb_get(f"users/{owner_uid}")
    correct_password = owner_data.get("password", "")

    if entered != correct_password:
        # Spam + redirect
        for _ in range(3):
            await update.message.reply_text("🚫 *WRONG PASSWORD! Access Denied!*", parse_mode="Markdown")
        await update.message.reply_text(
            "⛔ Multiple wrong attempts detected. Returning to home...",
            reply_markup=get_home_keyboard()
        )
        return MAIN_MENU

    # Correct — show the account
    accounts = owner_data.get("accounts", {})
    acc = accounts.get(name, {})
    msg = (
        f"📋 *Account:* `{name}`\n\n"
        f"👤 Username: `{acc.get('username', 'N/A')}`\n"
        f"🔑 Password: `{acc.get('password', 'N/A')}`\n"
    )
    if acc.get("2fa"):
        msg += f"🔐 2FA Key: `{acc.get('2fa')}`\n"
    else:
        msg += "🔐 2FA: Not set\n"

    await update.message.reply_text(msg, parse_mode="Markdown")
    return MAIN_MENU

# ─────────────────────────────────────────────
# /remove <name> COMMAND
# ─────────────────────────────────────────────
async def remove_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_user.id

    if not is_logged_in(chat_id):
        await update.message.reply_text("Please /start and login first.")
        return MAIN_MENU

    if not context.args:
        await update.message.reply_text("Usage: `/remove <account_name>`", parse_mode="Markdown")
        return MAIN_MENU

    name = context.args[0].strip()
    acc = fb_get(f"users/{chat_id}/accounts/{name}")
    if not acc:
        await update.message.reply_text(f"❌ No account named *{name}* found.", parse_mode="Markdown")
        return MAIN_MENU

    fb_delete(f"users/{chat_id}/accounts/{name}")
    await update.message.reply_text(
        f"🗑️ Account *{name}* has been removed.",
        parse_mode="Markdown",
        reply_markup=get_home_keyboard()
    )
    return MAIN_MENU

# ─────────────────────────────────────────────
# CANCEL
# ─────────────────────────────────────────────
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.", reply_markup=get_home_keyboard())
    return MAIN_MENU

# ─────────────────────────────────────────────
# FALLBACK for logged-in users typing anything
# ─────────────────────────────────────────────
async def fallback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_user.id
    if is_logged_in(chat_id):
        await update.message.reply_text(
            "🤔 Unknown command. Use the menu buttons or:\n"
            "• `/account <name>` — view saved account\n"
            "• `/remove <name>` — delete saved account",
            parse_mode="Markdown",
            reply_markup=get_home_keyboard()
        )
    else:
        await update.message.reply_text("Please use /start to begin.")
    return MAIN_MENU

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(signup_start, pattern="^signup$"),
                CallbackQueryHandler(login_start, pattern="^login$"),
                MessageHandler(filters.Regex("^📑 𝙎𝙖𝙫𝙚 𝘼𝙘𝙘𝙤𝙪𝙣𝙩$"), menu_handler),
                MessageHandler(filters.Regex("^💝 𝙔𝙤𝙪𝙧 𝘼𝙘𝙘𝙤𝙪𝙣𝙩'𝙨$"), menu_handler),
                CommandHandler("account", view_account),
                CommandHandler("remove", remove_account),
                MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_handler),
            ],
            SIGNUP_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, signup_username)],
            SIGNUP_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, signup_password)],
            LOGIN_USERNAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, login_username)],
            LOGIN_PASSWORD:  [MessageHandler(filters.TEXT & ~filters.COMMAND, login_password)],
            SAVE_ACC_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, save_acc_name)],
            SAVE_ACC_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_acc_username)],
            SAVE_ACC_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_acc_password)],
            SAVE_ACC_2FA:      [MessageHandler(filters.TEXT & ~filters.COMMAND, save_acc_2fa)],
            VERIFY_PASSWORD:   [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_password_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv)

    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
    
