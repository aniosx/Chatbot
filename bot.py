import os
import json
import random
import logging
from dotenv import load_dotenv
from telegram import Update, ChatAction
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# إعدادات اللوج
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
PORT = int(os.getenv("PORT", 10000))
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD")

users_data_file = "users.json"
state_file = "state.json"

# تحميل المستخدمين
def load_user_data():
    if os.path.exists(users_data_file):
        with open(users_data_file, "r") as f:
            return json.load(f)
    return {}

# حفظ المستخدمين
def save_user_data():
    with open(users_data_file, "w") as f:
        json.dump(users_data, f)

# تحميل حالة البوت
def load_state():
    if os.path.exists(state_file):
        with open(state_file, "r") as f:
            return json.load(f)
    return {"password_enabled": False}

# حفظ حالة البوت
def save_state():
    with open(state_file, "w") as f:
        json.dump(state, f)

users_data = load_user_data()
state = load_state()
message_counts = {}

# توليد معرف عشوائي
def generate_alias():
    return f"مستخدم{random.randint(1000, 9999)}"

# التحقق من السبام
def check_spam(chat_id):
    from time import time
    now = int(time())
    if chat_id not in message_counts:
        message_counts[chat_id] = []
    # تنظيف الرسائل القديمة
    message_counts[chat_id] = [t for t in message_counts[chat_id] if now - t < 60]
    if len(message_counts[chat_id]) >= 6:
        return False
    message_counts[chat_id].append(now)
    return True

# إرسال رسالة لجميع المستخدمين
def broadcast_message(sender_id, text, context: CallbackContext):
    sender_alias = users_data[sender_id]["alias"]
    for user_id, info in users_data.items():
        if int(user_id) != sender_id and not info.get("blocked", False):
            try:
                context.bot.send_message(chat_id=int(user_id), text=f"{sender_alias}: {text}")
            except Exception as e:
                print(f"فشل في إرسال رسالة إلى {user_id}: {e}")

# معالجة الرسائل
def handle_message(update: Update, context: CallbackContext):
    chat_id = str(update.effective_chat.id)
    message_text = update.message.text

    if chat_id not in users_data:
        alias = generate_alias()
        users_data[chat_id] = {"alias": alias, "joined": False, "blocked": False}
        save_user_data()

    user = users_data[chat_id]

    # إذا كانت كلمة المرور مفعّلة
    if state.get("password_enabled", False):
        if not user.get("joined"):
            if message_text == ACCESS_PASSWORD:
                user["joined"] = True
                users_data[chat_id] = user  # <-- هذا السطر مهم لتحديث المستخدم
                save_user_data()
                update.message.reply_text("تم قبول كلمة المرور. يمكنك الآن الدردشة.")
            else:
                update.message.reply_text("ادخل كلمة المرور للانضمام.")
            return

    if user.get("blocked", False):
        update.message.reply_text("لقد تم حظرك من استخدام البوت.")
        return

    if not check_spam(chat_id):
        update.message.reply_text("تم تجاوز الحد المسموح به (6 رسائل في الدقيقة). الرجاء الانتظار.")
        return

    if update.message.sticker or update.message.video or update.message.document:
        update.message.reply_text("نوع الرسالة غير مدعوم. الرجاء إرسال نص أو صورة فقط.")
        return

    if update.message.photo:
        broadcast_message(int(chat_id), "[صورة تم إرسالها]", context)
        return

    broadcast_message(int(chat_id), message_text, context)

# أوامر الإدارة
def start(update: Update, context: CallbackContext):
    chat_id = str(update.effective_chat.id)
    if chat_id not in users_data:
        alias = generate_alias()
        users_data[chat_id] = {"alias": alias, "joined": not state.get("password_enabled", False), "blocked": False}
        save_user_data()
    update.message.reply_text("مرحبًا! يمكنك الآن إرسال رسائل مجهولة.")

def list_users(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    msg = "المستخدمون:\n"
    for uid, info in users_data.items():
        status = "محظور" if info.get("blocked") else "نشط"
        msg += f"{info['alias']} (ID: {uid}) - {status}\n"
    update.message.reply_text(msg)

def block_user(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    if len(context.args) != 1:
        update.message.reply_text("استخدم: /block <alias>")
        return
    alias = context.args[0]
    for uid, info in users_data.items():
        if info["alias"] == alias:
            users_data[uid]["blocked"] = True
            save_user_data()
            update.message.reply_text(f"تم حظر {alias}")
            return
    update.message.reply_text("لم يتم العثور على المستخدم.")

def unblock_user(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    if len(context.args) != 1:
        update.message.reply_text("استخدم: /unblock <alias>")
        return
    alias = context.args[0]
    for uid, info in users_data.items():
        if info["alias"] == alias:
            users_data[uid]["blocked"] = False
            save_user_data()
            update.message.reply_text(f"تم رفع الحظر عن {alias}")
            return
    update.message.reply_text("لم يتم العثور على المستخدم.")

def toggle_password(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    state["password_enabled"] = not state.get("password_enabled", False)
    save_state()
    msg = "تم تفعيل كلمة المرور." if state["password_enabled"] else "تم إلغاء كلمة المرور."
    update.message.reply_text(msg)

def broadcast(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    text = ' '.join(context.args)
    for uid, info in users_data.items():
        try:
            context.bot.send_message(chat_id=int(uid), text=f"[رسالة إدارية]: {text}")
        except:
            continue

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("users", list_users))
    dp.add_handler(CommandHandler("block", block_user))
    dp.add_handler(CommandHandler("unblock", unblock_user))
    dp.add_handler(CommandHandler("togglepassword", toggle_password))
    dp.add_handler(CommandHandler("broadcast", broadcast))
    dp.add_handler(MessageHandler(Filters.text | Filters.photo | Filters.document | Filters.video | Filters.sticker, handle_message))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
