import os
import json
import random
import time
from dotenv import load_dotenv
from telegram import Update, ForceReply
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD")
PORT = int(os.getenv("PORT", 10000))

USERS_FILE = "users.json"
SETTINGS_FILE = "settings.json"

if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, "w") as f:
        json.dump({}, f)

if not os.path.exists(SETTINGS_FILE):
    with open(SETTINGS_FILE, "w") as f:
        json.dump({"password_required": True}, f)


def load_users():
    with open(USERS_FILE, "r") as f:
        return json.load(f)


def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f)


def load_settings():
    with open(SETTINGS_FILE, "r") as f:
        return json.load(f)


def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)


def get_new_alias(users):
    while True:
        alias = f"{random.randint(1000, 9999)}"
        if alias not in [u["alias"] for u in users.values()]:
            return alias


def start(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    users = load_users()
    settings = load_settings()

    if user_id not in users:
        if settings["password_required"]:
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text="يرجى إدخال كلمة المرور باستخدام الأمر:\n/password كلمتك")
            return
        alias = get_new_alias(users)
        users[user_id] = {
            "alias": alias,
            "blocked": False,
            "last_messages": []
        }
        save_users(users)
        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text=f"مرحبًا بك في الدردشة! رقمك هو: {alias}")

    else:
        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text=f"مرحبًا مجددًا! رقمك هو: {users[user_id]['alias']}")


def password(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    users = load_users()

    if user_id in users:
        update.message.reply_text("أنت بالفعل مسجل.")
        return

    if len(context.args) == 0:
        update.message.reply_text("يرجى كتابة كلمة المرور بعد الأمر.")
        return

    input_pass = context.args[0]
    if input_pass == ACCESS_PASSWORD:
        alias = get_new_alias(users)
        users[user_id] = {
            "alias": alias,
            "blocked": False,
            "last_messages": []
        }
        save_users(users)
        update.message.reply_text(f"تم تسجيلك بنجاح! رقمك هو: {alias}")
    else:
        update.message.reply_text("كلمة المرور غير صحيحة.")


def admin_only(func):
    def wrapper(update: Update, context: CallbackContext):
        if update.effective_user.id != OWNER_ID:
            update.message.reply_text("هذا الأمر مخصص للمسؤول فقط.")
            return
        return func(update, context)
    return wrapper


@admin_only
def toggle_password(update: Update, context: CallbackContext):
    settings = load_settings()
    settings["password_required"] = not settings["password_required"]
    save_settings(settings)
    state = "مفعلة" if settings["password_required"] else "معطلة"
    update.message.reply_text(f"تم تغيير حالة كلمة المرور إلى: {state}")


@admin_only
def list_users(update: Update, context: CallbackContext):
    users = load_users()
    msg = "المستخدمون:\n"
    for uid, data in users.items():
        status = "محظور" if data["blocked"] else "نشط"
        msg += f"رقم {data['alias']} - {status}\n"
    update.message.reply_text(msg)


@admin_only
def block_user(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("يرجى تحديد رقم المستخدم.")
        return
    alias = context.args[0]
    users = load_users()
    for uid, data in users.items():
        if data["alias"] == alias:
            data["blocked"] = True
            save_users(users)
            update.message.reply_text(f"تم حظر المستخدم {alias}")
            return
    update.message.reply_text("المستخدم غير موجود.")


@admin_only
def unblock_user(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("يرجى تحديد رقم المستخدم.")
        return
    alias = context.args[0]
    users = load_users()
    for uid, data in users.items():
        if data["alias"] == alias:
            data["blocked"] = False
            save_users(users)
            update.message.reply_text(f"تم رفع الحظر عن المستخدم {alias}")
            return
    update.message.reply_text("المستخدم غير موجود.")


@admin_only
def broadcast(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("يرجى كتابة الرسالة.")
        return
    users = load_users()
    msg = " ".join(context.args)
    for uid in users:
        try:
            context.bot.send_message(chat_id=int(uid), text=f"رسالة من المسؤول:\n{msg}")
        except:
            continue
    update.message.reply_text("تم إرسال الرسالة لجميع المستخدمين.")


def handle_message(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    users = load_users()

    if user_id not in users:
        update.message.reply_text("يرجى استخدام /start أولاً.")
        return

    if users[user_id]["blocked"]:
        update.message.reply_text("أنت محظور من استخدام البوت.")
        return

    now = time.time()
    timestamps = users[user_id].get("last_messages", [])
    timestamps = [t for t in timestamps if now - t < 60]

    if len(timestamps) >= 6:
        update.message.reply_text("تم تجاوز الحد المسموح به (6 رسائل في الدقيقة). انتظر قليلاً.")
        return

    timestamps.append(now)
    users[user_id]["last_messages"] = timestamps
    save_users(users)

    text = update.message.text
    alias = users[user_id]["alias"]

    for uid, data in users.items():
        if uid != user_id and not data["blocked"]:
            try:
                context.bot.send_message(chat_id=int(uid), text=f"{alias}: {text}")
            except:
                continue


def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("password", password))
    dp.add_handler(CommandHandler("toggle_password", toggle_password))
    dp.add_handler(CommandHandler("users", list_users))
    dp.add_handler(CommandHandler("block", block_user))
    dp.add_handler(CommandHandler("unblock", unblock_user))
    dp.add_handler(CommandHandler("broadcast", broadcast))

    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
