import telebot
import firebase_admin
from firebase_admin import credentials, db
import json
import os
import re
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# Railway variable থেকে Firebase config নেওয়া
firebase_json = os.environ.get("FIREBASE_CONFIG")
if not firebase_json:
    raise Exception("FIREBASE_CONFIG environment variable not found!")

firebase_config = json.loads(firebase_json)

# Firebase Admin SDK initialization
cred = credentials.Certificate(firebase_config)
firebase_admin.initialize_app(cred, {
    'databaseURL': f"https://{firebase_config['project_id']}.firebaseio.com/"
})

# Bot token
BOT_TOKEN = os.environ.get("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")

# Helper Functions
def is_logged_in(user_id):
    ref = db.reference(f'users/{user_id}')
    user = ref.get()
    return user.get("logged_in", False) if user else False

def get_user_data(user_id):
    ref = db.reference(f'users/{user_id}')
    return ref.get()

def save_account(user_id, account_name, username, password, twofa):
    ref = db.reference(f'accounts/{user_id}/{account_name}')
    ref.set({
        "username": username,
        "password": password,
        "twofa": twofa if twofa != "none" else None
    })
    return True

def get_all_accounts(user_id):
    ref = db.reference(f'accounts/{user_id}')
    accounts = ref.get()
    if accounts:
        return list(accounts.keys())
    return []

def get_account_details(user_id, account_name):
    ref = db.reference(f'accounts/{user_id}/{account_name}')
    return ref.get()

def delete_account(user_id, account_name):
    ref = db.reference(f'accounts/{user_id}/{account_name}')
    ref.delete()
    return True

# Main Menu Keyboard
def main_menu_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = KeyboardButton("📑 Save Account")
    btn2 = KeyboardButton("💝 Your Account's")
    keyboard.add(btn1, btn2)
    return keyboard

# Start Command
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.chat.id
    name = message.from_user.first_name
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    signup_btn = InlineKeyboardButton("📋 Sign Up", callback_data="signup")
    login_btn = InlineKeyboardButton("🎉 Login", callback_data="login")
    keyboard.add(signup_btn, login_btn)
    
    bot.send_message(
        user_id,
        f"🎯 হ্যালো {name}! 👋\n\n"
        f"🔥 এটি একটি **Account Saver Bot**\n"
        f"💾 এখানে আপনার বিভিন্ন অ্যাকাউন্ট সংরক্ষণ করুন\n\n"
        f"✏️ শুরু করতে নিচের Sign Up বা Login এ ক্লিক করুন:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

# Sign Up & Login
@bot.callback_query_handler(func=lambda call: call.data in ["signup", "login"])
def auth_handler(call):
    user_id = call.message.chat.id
    
    if call.data == "signup":
        msg = bot.send_message(user_id, "🔐 আপনার ইউজারনেম লিখুন (শুধু ইংরেজি অক্ষর ও সংখ্যা):")
        bot.register_next_step_handler(msg, signup_username)
    else:
        user_data = get_user_data(user_id)
        if user_data and user_data.get("password"):
            msg = bot.send_message(user_id, "🔑 আপনার পাসওয়ার্ড লিখুন:")
            bot.register_next_step_handler(msg, login_password)
        else:
            bot.send_message(user_id, "❌ আপনার কোন একাউন্ট নেই! প্রথমে /start দিয়ে Sign Up করুন।")

def signup_username(message):
    user_id = message.chat.id
    username = message.text.strip()
    
    if not re.match("^[a-zA-Z0-9_]+$", username):
        bot.send_message(user_id, "❌ ইউজারনেম শুধু ইংরেজি অক্ষর, সংখ্যা ও আন্ডারস্কোর থাকতে পারে। আবার চেষ্টা করুন:")
        msg = bot.send_message(user_id, "ইউজারনেম লিখুন:")
        bot.register_next_step_handler(msg, signup_username)
        return
    
    temp_ref = db.reference(f'temp/{user_id}')
    temp_ref.set({"username": username})
    msg = bot.send_message(user_id, "🔒 আপনার পাসওয়ার্ড লিখুন (মিনিমাম ৪ অক্ষর):")
    bot.register_next_step_handler(msg, signup_password)

def signup_password(message):
    user_id = message.chat.id
    password = message.text.strip()
    
    if len(password) < 4:
        bot.send_message(user_id, "❌ পাসওয়ার্ড কমপক্ষে ৪ অক্ষরের হতে হবে। আবার লিখুন:")
        msg = bot.send_message(user_id, "পাসওয়ার্ড লিখুন:")
        bot.register_next_step_handler(msg, signup_password)
        return
    
    temp_ref = db.reference(f'temp/{user_id}')
    temp_data = temp_ref.get()
    username = temp_data.get("username")
    
    user_ref = db.reference(f'users/{user_id}')
    user_ref.set({
        "username": username,
        "password": password,
        "logged_in": True
    })
    
    temp_ref.delete()
    
    chat_full_name = f"{message.from_user.first_name} {message.from_user.last_name if message.from_user.last_name else ''}"
    admin_msg = (
        f"🆕 **নতুন ইউজার সাইনআপ করেছে!**\n\n"
        f"👤 নাম: {chat_full_name}\n"
        f"🆔 ইউজারনেম: @{message.from_user.username if message.from_user.username else 'N/A'}\n"
        f"📱 চ্যাট আইডি: `{user_id}`\n"
        f"🔐 সেট করা ইউজারনেম: {username}"
    )
    bot.send_message(ADMIN_CHAT_ID, admin_msg, parse_mode="Markdown")
    
    bot.send_message(user_id, "✅ সফলভাবে অ্যাকাউন্ট তৈরি হয়েছে! 🎉", reply_markup=main_menu_keyboard())

def login_password(message):
    user_id = message.chat.id
    password = message.text.strip()
    
    user_data = get_user_data(user_id)
    if user_data and user_data.get("password") == password:
        user_ref = db.reference(f'users/{user_id}')
        user_ref.update({"logged_in": True})
        bot.send_message(user_id, "✅ লগইন সফল! স্বাগতম 🤗", reply_markup=main_menu_keyboard())
    else:
        bot.send_message(user_id, "❌ ভুল পাসওয়ার্ড! আবার চেষ্টা করুন। /start দিয়ে চেষ্টা করুন।")

# Save Account
@bot.message_handler(func=lambda message: message.text == "📑 Save Account")
def save_account_start(message):
    user_id = message.chat.id
    if not is_logged_in(user_id):
        bot.send_message(user_id, "⚠️ আপনাকে প্রথমে লগইন করতে হবে। /start দিন।")
        return
    
    msg = bot.send_message(user_id, "🏷️ এই অ্যাকাউন্টের জন্য একটি **নাম** নির্বাচন করুন (যেমন: gmail, fb, github):")
    bot.register_next_step_handler(msg, get_account_name)

def get_account_name(message):
    user_id = message.chat.id
    account_name = message.text.strip().lower()
    
    acc_ref = db.reference(f'accounts/{user_id}/{account_name}')
    existing = acc_ref.get()
    if existing:
        bot.send_message(user_id, "⚠️ এই নামে আগেই একটি অ্যাকাউন্ট আছে! ভিন্ন নাম দিন।")
        msg = bot.send_message(user_id, "নতুন নাম লিখুন:")
        bot.register_next_step_handler(msg, get_account_name)
        return
    
    temp_ref = db.reference(f'temp_save/{user_id}')
    temp_ref.set({"acc_name": account_name})
    msg = bot.send_message(user_id, "👤 ইউজারনেম লিখুন:")
    bot.register_next_step_handler(msg, get_username)

def get_username(message):
    user_id = message.chat.id
    username = message.text.strip()
    temp_ref = db.reference(f'temp_save/{user_id}')
    temp_ref.update({"username": username})
    msg = bot.send_message(user_id, "🔑 পাসওয়ার্ড লিখুন:")
    bot.register_next_step_handler(msg, get_password)

def get_password(message):
    user_id = message.chat.id
    password = message.text.strip()
    temp_ref = db.reference(f'temp_save/{user_id}')
    temp_ref.update({"password": password})
    msg = bot.send_message(user_id, "🔐 2FA কী লিখুন (যদি না থাকে 'none' লিখুন):")
    bot.register_next_step_handler(msg, get_twofa)

def get_twofa(message):
    user_id = message.chat.id
    twofa = message.text.strip()
    temp_ref = db.reference(f'temp_save/{user_id}')
    temp_data = temp_ref.get()
    
    if temp_data:
        save_account(
            user_id,
            temp_data["acc_name"],
            temp_data["username"],
            temp_data["password"],
            twofa
        )
        temp_ref.delete()
        bot.send_message(user_id, f"✅ অ্যাকাউন্ট `{temp_data['acc_name']}` সফলভাবে সংরক্ষণ করা হয়েছে!", parse_mode="Markdown")
    else:
        bot.send_message(user_id, "❌ কিছু ভুল হয়েছে! আবার চেষ্টা করুন।")

# Your Account's
@bot.message_handler(func=lambda message: message.text == "💝 Your Account's")
def show_accounts(message):
    user_id = message.chat.id
    if not is_logged_in(user_id):
        bot.send_message(user_id, "⚠️ লগইন করুন প্রথমে!")
        return
    
    accounts = get_all_accounts(user_id)
    if not accounts:
        bot.send_message(user_id, "📭 এখনও কোনো অ্যাকাউন্ট সংরক্ষণ করা হয়নি।\n'📑 Save Account' দিয়ে সংরক্ষণ করুন।")
        return
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    for acc in accounts:
        btn = InlineKeyboardButton(acc.capitalize(), callback_data=f"view_{acc}")
        keyboard.add(btn)
    
    keyboard.add(InlineKeyboardButton("🗑️ অ্যাকাউন্ট ডিলিট", callback_data="delete_menu"))
    keyboard.add(InlineKeyboardButton("🔙 মেনুতে ফিরুন", callback_data="back_to_menu"))
    
    bot.send_message(user_id, "📋 আপনার সংরক্ষিত অ্যাকাউন্টগুলোর তালিকা:", reply_markup=keyboard)

# View Account with Security
@bot.callback_query_handler(func=lambda call: call.data.startswith("view_"))
def view_account(call):
    user_id = call.message.chat.id
    account_name = call.data.split("_", 1)[1]
    
    temp_ref = db.reference(f'temp_view/{user_id}')
    temp_ref.set({"account": account_name})
    
    bot.send_message(user_id, f"🔒 নিরাপত্তার জন্য আপনার মাস্টার পাসওয়ার্ড দিন:\n(যেটি Sign Up এ দিয়েছিলেন)")
    msg = bot.send_message(user_id, "পাসওয়ার্ড লিখুন:")
    bot.register_next_step_handler(msg, verify_master_password)

def verify_master_password(message):
    user_id = message.chat.id
    entered_pass = message.text.strip()
    
    user_data = get_user_data(user_id)
    if user_data and user_data.get("password") == entered_pass:
        temp_ref = db.reference(f'temp_view/{user_id}')
        temp_data = temp_ref.get()
        if temp_data:
            acc_name = temp_data["account"]
            acc_details = get_account_details(user_id, acc_name)
            if acc_details:
                twofa_text = f"🔐 2FA: `{acc_details['twofa']}`" if acc_details.get('twofa') else "🔐 2FA: নেই"
                msg_text = (
                    f"📁 **অ্যাকাউন্ট:** `{acc_name}`\n\n"
                    f"👤 ইউজারনেম: `{acc_details['username']}`\n"
                    f"🔑 পাসওয়ার্ড: `{acc_details['password']}`\n"
                    f"{twofa_text}"
                )
                bot.send_message(user_id, msg_text, parse_mode="Markdown")
            else:
                bot.send_message(user_id, "❌ অ্যাকাউন্ট পাওয়া যায়নি!")
        temp_ref.delete()
    else:
        bot.send_message(user_id, "⚠️ **ভুল পাসওয়ার্ড!** অননুমোদিত প্রবেশ আটকানো হয়েছে।", parse_mode="Markdown")
        bot.send_message(user_id, "🏠 হোম মেনুতে ফিরে আসছেন...", reply_markup=main_menu_keyboard())

# Delete Menu
@bot.callback_query_handler(func=lambda call: call.data == "delete_menu")
def delete_menu(call):
    user_id = call.message.chat.id
    accounts = get_all_accounts(user_id)
    if not accounts:
        bot.send_message(user_id, "📭 ডিলিট করার মতো কোনো অ্যাকাউন্ট নেই।")
        return
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    for acc in accounts:
        btn = InlineKeyboardButton(f"🗑️ {acc}", callback_data=f"del_{acc}")
        keyboard.add(btn)
    keyboard.add(InlineKeyboardButton("🔙 পেছনে", callback_data="back_to_accounts"))
    
    bot.edit_message_text("🗑️ ডিলিট করার জন্য অ্যাকাউন্ট নির্বাচন করুন:", user_id, call.message.message_id, reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith("del_"))
def confirm_delete(call):
    user_id = call.message.chat.id
    account_name = call.data.split("_", 1)[1]
    
    delete_account(user_id, account_name)
    bot.answer_callback_query(call.id, f"{account_name} ডিলিট করা হয়েছে!")
    
    accounts = get_all_accounts(user_id)
    if accounts:
        keyboard = InlineKeyboardMarkup(row_width=2)
        for acc in accounts:
            keyboard.add(InlineKeyboardButton(acc.capitalize(), callback_data=f"view_{acc}"))
        keyboard.add(InlineKeyboardButton("🗑️ অ্যাকাউন্ট ডিলিট", callback_data="delete_menu"))
        keyboard.add(InlineKeyboardButton("🔙 মেনুতে ফিরুন", callback_data="back_to_menu"))
        bot.edit_message_text("✅ ডিলিট সম্পন্ন! বর্তমান অ্যাকাউন্ট তালিকা:", user_id, call.message.message_id, reply_markup=keyboard)
    else:
        bot.edit_message_text("📭 এখন কোনো অ্যাকাউন্ট নেই।", user_id, call.message.message_id)
        bot.send_message(user_id, "🔙 মেনু:", reply_markup=main_menu_keyboard())

# Back to Menu
@bot.callback_query_handler(func=lambda call: call.data == "back_to_menu")
def back_to_menu(call):
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    bot.send_message(call.message.chat.id, "🔙 মূল মেনু:", reply_markup=main_menu_keyboard())

@bot.callback_query_handler(func=lambda call: call.data == "back_to_accounts")
def back_to_accounts(call):
    show_accounts(call.message)

# Remove Command
@bot.message_handler(commands=['remove'])
def remove_command(message):
    user_id = message.chat.id
    if not is_logged_in(user_id):
        bot.send_message(user_id, "লগইন করুন প্রথমে!")
        return
    
    parts = message.text.split()
    if len(parts) != 2:
        bot.send_message(user_id, "⚠️ ব্যবহার: `/remove account_name`", parse_mode="Markdown")
        return
    
    acc_name = parts[1].lower()
    acc = get_account_details(user_id, acc_name)
    if acc:
        delete_account(user_id, acc_name)
        bot.send_message(user_id, f"✅ `{acc_name}` ডিলিট করা হয়েছে!", parse_mode="Markdown")
    else:
        bot.send_message(user_id, "❌ এই নামে কোনো অ্যাকাউন্ট নেই!")

# Run Bot
if __name__ == "__main__":
    print("🤖 Bot is running with Firebase Admin SDK...")
    bot.infinity_polling()
