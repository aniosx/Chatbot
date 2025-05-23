import os import json import logging from uuid import uuid4 from flask import Flask, request from telegram import Update, InputFile from telegram.ext import (Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackContext)

TOKEN = os.getenv("BOT_TOKEN") PORT = int(os.environ.get("PORT", 5000))

كلمة السر الابتدائية (من متغير البيئة)

INITIAL_PASSWORD = os.getenv("ACCESS_PASSWORD", "") ACCESS_PASSWORD = INITIAL_PASSWORD

المسارات

STATE_FILE = "state.json" USERS_FILE = "users.json" BLOCKED_FILE = "blocked_users.json"

إعداد السجل

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO) logger = logging.getLogger(name)

تهيئة Flask

app = Flask(name)

تهيئة البيانات

state = {"authorized": [], "admin_id": None} users = {} blocked_users = []

تحميل البيانات

if os.path.exists(STATE_FILE): with open(STATE_FILE, "r") as f: state = json.load(f)

if os.path.exists(USERS_FILE): with open(USERS_FILE, "r") as f: users = json.load(f)

if os.path.exists(BLOCKED_FILE): with open(BLOCKED_FILE, "r") as f: blocked_users = json.load(f)

def save_state(): with open(STATE_FILE, "w") as f: json.dump(state, f) with open(USERS_FILE, "w") as f: json.dump(users, f) with open(BLOCKED_FILE, "w") as f: json.dump(blocked_users, f)

أمر /start

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE): user_id = str(update.effective_user.id) if user_id in blocked_users: await update.message.reply_text("لقد تم حظرك من استخدام هذا البوت.") return

if ACCESS_PASSWORD and user_id not in state["authorized"]:
    await update.message.reply_text("الرجاء إدخال كلمة المرور للولوج إلى البوت.")
    return

if user_id not in users:
    random_id = str(uuid4())[:8]
    users[user_id] = {"random_id": random_id}
    save_state()

await update.message.reply_text("مرحبًا بك! أرسل رسالة ليتم نشرها للمجموعة.")

أمر /setpassword

async def set_password(update: Update, context: ContextTypes.DEFAULT_TYPE): global ACCESS_PASSWORD user_id = str(update.effective_user.id) if user_id != str(state["admin_id"]): await update.message.reply_text("ليس لديك صلاحية تنفيذ هذا الأمر.") return

if context.args:
    ACCESS_PASSWORD = context.args[0]
    await update.message.reply_text(f"تم تعيين كلمة المرور الجديدة: {ACCESS_PASSWORD}")
else:
    ACCESS_PASSWORD = ""
    await update.message.reply_text("تم حذف كلمة المرور بنجاح.")

أمر /usersfile

async def users_file(update: Update, context: ContextTypes.DEFAULT_TYPE): user_id = str(update.effective_user.id) if user_id != str(state["admin_id"]): await update.message.reply_text("ليس لديك صلاحية.") return

text = "\n".join([f"{uid}: {data['random_id']}" for uid, data in users.items()])
with open("all_users.txt", "w") as f:
    f.write(text)
await context.bot.send_document(chat_id=update.effective_chat.id, document=InputFile("all_users.txt"))

أمر /blocked

async def show_blocked(update: Update, context: ContextTypes.DEFAULT_TYPE): user_id = str(update.effective_user.id) if user_id != str(state["admin_id"]): await update.message.reply_text("ليس لديك صلاحية.") return if not blocked_users: await update.message.reply_text("لا يوجد مستخدمون محظورون.") return text = "\n".join([f"{uid}: {users.get(uid, {}).get('random_id', 'غير معروف')}" for uid in blocked_users]) await update.message.reply_text("المستخدمون المحظورون:\n" + text)

أوامر الإدارة

async def block(update: Update, context: ContextTypes.DEFAULT_TYPE): user_id = str(update.effective_user.id) if user_id != str(state["admin_id"]): await update.message.reply_text("ليس لديك صلاحية.") return if context.args: to_block = context.args[0] if to_block not in blocked_users: blocked_users.append(to_block) save_state() await update.message.reply_text("تم حظر المستخدم.") else: await update.message.reply_text("المستخدم محظور بالفعل.")

async def unblock(update: Update, context: ContextTypes.DEFAULT_TYPE): user_id = str(update.effective_user.id) if user_id != str(state["admin_id"]): await update.message.reply_text("ليس لديك صلاحية.") return if context.args: to_unblock = context.args[0] if to_unblock in blocked_users: blocked_users.remove(to_unblock) save_state() await update.message.reply_text("تم مسح الحظر عن المستخدم.") else: await update.message.reply_text("المستخدم غير محظور.")

التعامل مع الرسائل

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE): user_id = str(update.effective_user.id) if user_id in blocked_users: await update.message.reply_text("لا يمكنك إرسال رسائل، لقد تم حظرك.") return

if ACCESS_PASSWORD and user_id not in state["authorized"]:
    text = update.message.text
    if text == ACCESS_PASSWORD:
        state["authorized"].append(user_id)
        save_state()
        await update.message.reply_text("تم الدخول بنجاح.")
    else:
        await update.message.reply_text("كلمة مرور خاطئة.")
    return

if user_id not in users:
    random_id = str(uuid4())[:8]
    users[user_id] = {"random_id": random_id}
    save_state()

sender_id = users[user_id]["random_id"]
caption = f"رسالة من مستخدم {sender_id}"

# إعادة توجيه حسب نوع الرسالة
if update.message.text:
    await context.bot.send_message(chat_id=state["admin_id"], text=f"{caption}:\n{update.message.text}")
elif update.message.photo:
    await context.bot.send_photo(chat_id=state["admin_id"], photo=update.message.photo[-1].file_id, caption=caption)
elif update.message.document:
    await context.bot.send_document(chat_id=state["admin_id"], document=update.message.document.file_id, caption=caption)
elif update.message.video:
    await context.bot.send_video(chat_id=state["admin_id"], video=update.message.video.file_id, caption=caption)
elif update.message.voice:
    await context.bot.send_voice(chat_id=state["admin_id"], voice=update.message.voice.file_id, caption=caption)
else:
    await update.message.reply_text("نوع الرسالة غير مدعوم.")

تهيئة التطبيق

async def main(): application = Application.builder().token(TOKEN).build()

# تسجيل المعالجين
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("setpassword", set_password))
application.add_handler(CommandHandler("blocked", show_blocked))
application.add_handler(CommandHandler("usersfile", users_file))
application.add_handler(CommandHandler("block", block))
application.add_handler(CommandHandler("unblock", unblock))
application.add_handler(MessageHandler(filters.ALL, handle_message))

# تشغيل polling أو webhook
if os.getenv("USE_POLLING") == "true":
    await application.run_polling()
else:
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}"
    )

if name == "main": import asyncio asyncio.run(main())

