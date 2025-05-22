import os
import json
import random
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# إعدادات
TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
PORT = int(os.getenv("PORT", "10000"))
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD", "pass123")

app = Flask(__name__)

# بيانات
USERS_FILE = "users.json"
STATE_FILE = "state.json"
MESSAGE_LIMIT = 6
TIME_WINDOW = 60  # ثانية

# تحميل أو إنشاء الملفات
def load_data(filename, default):
    if not os.path.exists(filename):
        with open(filename, "w") as f:
            json.dump(default, f)
    with open(filename, "r") as f:
        return json.load(f)

def save_data(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f)

users = load_data(USERS_FILE, {})
state = load_data(STATE_FILE, {"password_enabled": True})
message_times = {}

# إنشاء اسم وهمي عشوائي
def generate_alias():
    while True:
        alias = ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=4))
        if alias not in users.values():
            return alias

# معالجة الرسائل
def handle_message(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)

    if user_id not in users:
        if state.get("password_enabled", True):
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text="أدخل كلمة المرور للانضمام:")
            return
        alias = generate_alias()
        users[user_id] = alias
        save_data(USERS_FILE, users)
        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text=f"أهلاً بك! تم إعطاؤك الاسم: {alias}")
    elif user_id in blocked:
        return
    else:
        # الحماية من السبام
        now = context.job_queue._dispatcher.time()
        times = message_times.get(user_id, [])
        times = [t for t in times if now - t < TIME_WINDOW]
        if len(times) >= MESSAGE_LIMIT:
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text="تم منعك مؤقتاً من إرسال الرسائل لكثرة الإرسال.")
            return
        times.append(now)
        message_times[user_id] = times

        # إرسال الرسالة لجميع المستخدمين
        alias = users[user_id]
        text = f"{alias}: {update.message.text}"
        for uid in users:
            if uid != user_id and uid not in blocked:
                try:
                    context.bot.send_message(chat_id=int(uid), text=text)
                except:
                    continue

# أمر /start
def start(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    if user_id not in users:
        if state.get("password_enabled", True):
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text="مرحبًا! أدخل كلمة المرور للانضمام:")
        else:
            alias = generate_alias()
            users[user_id] = alias
            save_data(USERS_FILE, users)
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text=f"أهلاً بك! تم إعطاؤك الاسم: {alias}")
    else:
        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text="أنت مسجل مسبقاً.")

# أمر /password لإدخال كلمة المرور
def password(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    if not context.args:
        return update.message.reply_text("يرجى كتابة كلمة المرور بعد الأمر.")

    if ACCESS_PASSWORD and context.args[0] == ACCESS_PASSWORD:
        alias = generate_alias()
        users[user_id] = alias
        save_data(USERS_FILE, users)
        update.message.reply_text(f"تم تسجيلك! اسمك: {alias}")
    else:
        update.message.reply_text("كلمة المرور خاطئة.")

# قائمة المحظورين
blocked = set()

# أوامر الإدارة
def admin(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    update.message.reply_text("/users - عرض المستخدمين\n/block XXXX - حظر مستخدم\n/unblock XXXX - رفع الحظر\n/broadcast رسالة\n/password_toggle - تفعيل/تعطيل كلمة المرور")

def users_list(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    msg = "المستخدمون:\n"
    for uid, alias in users.items():
        status = "محظور" if uid in blocked else "نشط"
        msg += f"{alias} - {uid} - {status}\n"
    update.message.reply_text(msg)

def block(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        return update.message.reply_text("اكتب الاسم الوهمي بعد الأمر.")
    alias = context.args[0]
    uid = next((uid for uid, a in users.items() if a == alias), None)
    if uid:
        blocked.add(uid)
        update.message.reply_text(f"تم حظر {alias}")
    else:
        update.message.reply_text("لم يتم العثور على المستخدم.")

def unblock(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        return update.message.reply_text("اكتب الاسم الوهمي بعد الأمر.")
    alias = context.args[0]
    uid = next((uid for uid, a in users.items() if a == alias), None)
    if uid:
        blocked.discard(uid)
        update.message.reply_text(f"تم رفع الحظر عن {alias}")
    else:
        update.message.reply_text("لم يتم العثور على المستخدم.")

def broadcast(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    msg = " ".join(context.args)
    for uid in users:
        try:
            context.bot.send_message(chat_id=int(uid), text=f"رسالة من الإدارة:\n{msg}")
        except:
            continue
    update.message.reply_text("تم إرسال الرسالة.")

def password_toggle(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    state["password_enabled"] = not state.get("password_enabled", True)
    save_data(STATE_FILE, state)
    status = "مفعّلة" if state["password_enabled"] else "معطّلة"
    update.message.reply_text(f"تم تغيير حالة كلمة المرور إلى: {status}")

# Flask route
@app.route('/')
def index():
    return "البوت يعمل!"

# بدء Flask في Thread
def run_flask():
    app.run(host='0.0.0.0', port=PORT)

def main():
    threading.Thread(target=run_flask).start()

    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # الأوامر
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("password", password))
    dp.add_handler(CommandHandler("admin", admin))
    dp.add_handler(CommandHandler("users", users_list))
    dp.add_handler(CommandHandler("block", block))
    dp.add_handler(CommandHandler("unblock", unblock))
    dp.add_handler(CommandHandler("broadcast", broadcast))
    dp.add_handler(CommandHandler("password_toggle", password_toggle))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
