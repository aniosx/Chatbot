# -*- coding: utf-8 -*-
import json
import logging
import os
import random
import time
from telegram import Update, ForceReply
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from dotenv import load_dotenv

# تحميل المتغيرات من ملف .env إذا وُجد
load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
PORT = int(os.getenv("PORT", "8443"))
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD")
PASSWORD_REQUIRED = True

# إعداد السجل
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

USERS_FILE = "users.json"
users = {}
blocked = set()
msg_counter = {}
LIMIT = 6
INTERVAL = 60

def load_users():
    global users, blocked
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            users = data.get("users", {})
            blocked = set(data.get("blocked", []))
    except:
        users = {}
        blocked = set()

def save_users():
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump({"users": users, "blocked": list(blocked)}, f, ensure_ascii=False)

def get_alias(user_id):
    if str(user_id) not in users:
        alias = ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=4))
        while alias in users.values():
            alias = ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=4))
        users[str(user_id)] = alias
        save_users()
    return users[str(user_id)]

def is_rate_limited(user_id):
    now = time.time()
    counter = msg_counter.get(user_id, [])
    counter = [t for t in counter if now - t < INTERVAL]
    counter.append(now)
    msg_counter[user_id] = counter
    return len(counter) > LIMIT

def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if PASSWORD_REQUIRED and "authorized" not in context.user_data:
        update.message.reply_text("أدخل كلمة المرور للمتابعة:")
        context.user_data["awaiting_password"] = True
        return

    alias = get_alias(user_id)
    update.message.reply_text(f"مرحبًا بك في الدردشة الجماعية المجهولة! لقبك هو: {alias}")

def handle_message(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if str(user_id) in blocked:
        return

    if PASSWORD_REQUIRED and "authorized" not in context.user_data:
        if context.user_data.get("awaiting_password"):
            if update.message.text.strip() == ACCESS_PASSWORD:
                context.user_data["authorized"] = True
                context.user_data.pop("awaiting_password", None)
                alias = get_alias(user_id)
                update.message.reply_text(f"تم التحقق! لقبك هو: {alias}")
            else:
                update.message.reply_text("كلمة المرور غير صحيحة. حاول مرة أخرى.")
        else:
            update.message.reply_text("الرجاء إرسال /start للبدء.")
        return

    if is_rate_limited(user_id):
        update.message.reply_text("تم تجاوز الحد الأقصى للرسائل. الرجاء الانتظار قليلاً.")
        return

    alias = get_alias(user_id)
    text = update.message.text
    for uid in users:
        if str(uid) != str(user_id) and str(uid) not in blocked:
            try:
                context.bot.send_message(chat_id=int(uid), text=f"[{alias}]: {text}")
            except:
                continue

def block(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    if context.args:
        alias_to_block = context.args[0].upper()
        for uid, alias in users.items():
            if alias == alias_to_block:
                blocked.add(uid)
                save_users()
                update.message.reply_text(f"تم حظر المستخدم {alias_to_block}.")
                return
        update.message.reply_text("المستخدم غير موجود.")

def unblock(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    if context.args:
        alias_to_unblock = context.args[0].upper()
        for uid, alias in users.items():
            if alias == alias_to_unblock and uid in blocked:
                blocked.remove(uid)
                save_users()
                update.message.reply_text(f"تم رفع الحظر عن المستخدم {alias_to_unblock}.")
                return
        update.message.reply_text("المستخدم غير موجود أو غير محظور.")

def list_users(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    msg = "المستخدمون:
"
    for uid, alias in users.items():
        status = "محظور" if uid in blocked else "نشط"
        msg += f"{alias} - {status}
"
    update.message.reply_text(msg)

def toggle_password(update: Update, context: CallbackContext):
    global PASSWORD_REQUIRED
    if update.effective_user.id != OWNER_ID:
        return
    PASSWORD_REQUIRED = not PASSWORD_REQUIRED
    status = "مطلوب" if PASSWORD_REQUIRED else "غير مطلوب"
    update.message.reply_text(f"تم تغيير وضع كلمة المرور إلى: {status}")

def main():
    load_users()
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("block", block))
    dp.add_handler(CommandHandler("unblock", unblock))
    dp.add_handler(CommandHandler("users", list_users))
    dp.add_handler(CommandHandler("toggle_password", toggle_password))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
