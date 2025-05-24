#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import json
import random
import time
import logging
from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Updater, Dispatcher, CommandHandler, MessageHandler, Filters, CallbackContext

# ───── إعدادات أساسية ────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.DEBUG
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD", "").strip()
USE_WEBHOOK = os.getenv("USE_WEBHOOK", "False").lower() == "true"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
PORT = int(os.getenv("PORT", "8443"))

# ───── ملفات البيانات ───────────────────────────────
USERS_FILE = "users.json"

# تحميل users.json أو إنشاء ملف فارغ إذا لم يكن موجودًا
users_data = {}
if os.path.exists(USERS_FILE):
    logger.debug(f"Loading users from {USERS_FILE}")
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users_data = json.load(f)
        # إضافة first_message_sent إلى الإدخالات القديمة إذا كانت مفقودة
        for uid, info in users_data.items():
            if "first_message_sent" not in info:
                info["first_message_sent"] = False
        logger.debug(f"Loaded users: {len(users_data)} entries")
    except Exception as e:
        logger.error(f"Failed to load users: {e}", exc_info=True)
else:
    logger.debug(f"Creating new users file at {USERS_FILE}")
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=2)
        logger.debug("Users file created successfully")
    except Exception as e:
        logger.error(f"Failed to create users file: {e}", exc_info=True)
        raise

def save_users():
    logger.debug(f"Saving users to {USERS_FILE}")
    for attempt in range(3):  # محاولة الحفظ 3 مرات
        try:
            with open(USERS_FILE, "w", encoding="utf-8") as f:
                json.dump(users_data, f, ensure_ascii=False, indent=2)
            logger.debug("Users saved successfully")
            return True
        except Exception as e:
            logger.error(f"Attempt {attempt + 1} failed to save users: {e}", exc_info=True)
            time.sleep(0.5)  # تأخير قصير قبل المحاولة التالية
    logger.error("All attempts to save users failed")
    return False

def generate_alias():
    return "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=4))

# ───── حدود الرسائل والملفات ─────────────────────────
MAX_MESSAGES_PER_MINUTE = 5
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 ميغابايت

message_timestamps = {}  # user_id -> [timestamps]

def can_send(user_id):
    now = time.time()
    times = message_timestamps.get(user_id, [])
    times = [t for t in times if now - t < 60]
    if len(times) >= MAX_MESSAGES_PER_MINUTE:
        message_timestamps[user_id] = times
        return False
    times.append(now)
    message_timestamps[user_id] = times
    return True

# ───── إعداد البوت والفلاسك ───────────────────────────
bot = Bot(token=TOKEN)
updater = Updater(token=TOKEN, use_context=True)
dispatcher: Dispatcher = updater.dispatcher
app = Flask(__name__)

# ───── وظائف مساعدة ───────────────────────────────────
def is_password_required():
    return bool(ACCESS_PASSWORD)

def welcome_text(uid):
    alias = users_data[uid]["alias"]
    if is_password_required() and not users_data[uid]["pwd_ok"]:
        return f"🔒 أرسل كلمة المرور للانضمام يا {alias}."
    return f"🚀 مرحباً {alias}! يمكنك الآن الدردشة."

def broadcast_to_others(sender_id, func):
    success = False
    for uid, info in users_data.items():
        if uid != sender_id and info["joined"] and not info["blocked"]:
            try:
                func(int(uid))
                success = True
                time.sleep(0.033)  # تأخير 33 مللي ثانية
            except Exception as e:
                logger.warning(f"فشل إرسال رسالة إلى {uid}: {e}")
    return success

def is_admin(user_id):
    return user_id == OWNER_ID

# ───── الأوامر الأساسية ───────────────────────────────
def cmd_start(update: Update, context: CallbackContext):
    uid = str(update.effective_chat.id)
    logger.debug(f"Processing /start for user {uid}")
    is_new_user = uid not in users_data
    if is_new_user:
        logger.debug(f"New user {uid}, generating alias")
        users_data[uid] = {
            "alias": generate_alias(),
            "blocked": False,
            "joined": False,
            "pwd_ok": not is_password_required() or int(uid) == OWNER_ID,
            "last_msgs": [],
            "first_message_sent": False
        }
        # إخطار المشرف بالمستخدم الجديد
        try:
            user_info = update.effective_user
            bot.send_message(
                OWNER_ID,
                f"🆕 مستخدم جديد انضم!\n"
                f"المعرف: {users_data[uid]['alias']}\n"
                f"ID: {uid}\n"
                f"الاسم: {user_info.first_name or 'غير متوفر'}\n"
                f"اسم المستخدم: @{user_info.username or 'غير متوفر'}"
            )
        except Exception as e:
            logger.error(f"Failed to notify admin about new user {uid}: {e}")
        save_users()
    user = users_data[uid]
    logger.debug(f"User {uid} status: joined={user['joined']}, pwd_ok={user['pwd_ok']}, first_message_sent={user['first_message_sent']}")
    if user["joined"] and user["pwd_ok"]:
        update.message.reply_text(f"🚀 مرحبًا مجددًا {user['alias']}! أنت بالفعل في الدردشة.")
    else:
        user["joined"] = True
        if not is_password_required():
            user["pwd_ok"] = True
        save_users()
        update.message.reply_text(welcome_text(uid))

def handle_text(update: Update, context: CallbackContext):
    uid = str(update.effective_chat.id)
    text = update.message.text or ""
    if uid not in users_data:
        cmd_start(update, context)
        return
    user = users_data[uid]

    if user["blocked"]:
        update.message.reply_text("⚠️ تم حظرك، لا يمكنك إرسال الرسائل.")
        return

    if is_password_required() and not user["pwd_ok"] and int(uid) != OWNER_ID:
        if text.strip() == ACCESS_PASSWORD:
            user["pwd_ok"] = True
            user["joined"] = True
            save_users()
            update.message.reply_text("✅ تم قبول كلمة المرور. يمكنك الآن الدردشة.")
        else:
            update.message.reply_text("🔒 كلمة المرور خاطئة.")
        return

    if not user["joined"]:
        user["joined"] = True
        save_users()
        update.message.reply_text(f"✅ {user['alias']}، يمكنك الآن الدردشة.")
        return

    if not can_send(uid):
        update.message.reply_text("⚠️ تجاوزت 5 رسائل في الدقيقة. انتظر قليلاً.")
        return

    alias = user["alias"]
    is_first_message = not user.get("first_message_sent", False)
    success = broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[{alias}] {text}"))
    
    if is_first_message:
        logger.debug(f"First message detected for user {uid}")
        user["first_message_sent"] = True  # تحديث في الذاكرة أولاً
        if save_users():
            logger.debug(f"Successfully updated first_message_sent for user {uid}")
        else:
            logger.warning(f"Failed to save first_message_sent for user {uid}, but updated in memory")
        if success:
            update.message.reply_text("✅ رسالتك الأولى وصلت إلى المستخدمين الآخرين!")
        else:
            update.message.reply_text("❌ فشل إرسال رسالتك الأولى. حاول مرة أخرى لاحقًا.")

def handle_sticker(update: Update, context: CallbackContext):
    uid = str(update.effective_chat.id)
    user = users_data.get(uid)
    if not user or user["blocked"] or not user["joined"]:
        return
    sid = update.message.sticker.file_id
    alias = user["alias"]
    broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[{alias}] أرسل ستيكر:"))
    broadcast_to_others(uid, lambda cid: context.bot.send_sticker(cid, sticker=sid))

def handle_photo(update: Update, context: CallbackContext):
    uid = str(update.effective_chat.id)
    user = users_data.get(uid)
    if not user or user["blocked"] or not user["joined"]:
        return
    photo = update.message.photo[-1]
    if photo.file_size > MAX_FILE_SIZE:
        update.message.reply_text("❌ الصورة أكبر من 50 ميغابايت.")
        return
    fid = photo.file_id
    alias = user["alias"]
    broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[{alias}] أرسل صورة:"))
    broadcast_to_others(uid, lambda cid: context.bot.send_photo(cid, photo=fid))

def handle_video(update: Update, context: CallbackContext):
    uid = str(update.effective_chat.id)
    user = users_data.get(uid)
    if not user or user["blocked"] or not user["joined"]:
        return
    video = update.message.video
    if video.file_size > MAX_FILE_SIZE:
        update.message.reply_text("❌ الفيديو أكبر من 50 ميغابايت.")
        return
    vid = video.file_id
    alias = user["alias"]
    broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[{alias}] أرسل فيديو:"))
    broadcast_to_others(uid, lambda cid: context.bot.send_video(cid, video=vid))

def handle_audio(update: Update, context: CallbackContext):
    uid = str(update.effective_chat.id)
    user = users_data.get(uid)
    if not user or user["blocked"] or not user["joined"]:
        return
    audio = update.message.audio
    if audio.file_size > MAX_FILE_SIZE:
        update.message.reply_text("❌ الملف الصوتي أكبر من 50 ميغابايت.")
        return
    aid = audio.file_id
    alias = user["alias"]
    broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[{alias}] أرسل ملف صوتي:"))
    broadcast_to_others(uid, lambda cid: context.bot.send_audio(cid, audio=aid))

def handle_document(update: Update, context: CallbackContext):
    uid = str(update.effective_chat.id)
    user = users_data.get(uid)
    if not user or user["blocked"] or not user["joined"]:
        return
    doc = update.message.document
    if doc.file_size > MAX_FILE_SIZE:
        update.message.reply_text("❌ الملف أكبر من 50 ميغابايت.")
        return
    did = doc.file_id
    alias = user["alias"]
    broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[{alias}] أرسل ملف:"))
    broadcast_to_others(uid, lambda cid: context.bot.send_document(cid, document=did))

# ───── أوامر الإدارة ──────────────────────────────────────
def admin_only(func):
    def wrapper(update: Update, context: CallbackContext):
        if not is_admin(update.effective_user.id):
            update.message.reply_text("❌ أنت لست مشرفاً.")
            return
        return func(update, context)
    return wrapper

@admin_only
def cmd_block(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("Usage: /block ALIAS")
        return
    target = context.args[0]
    for uid, info in users_data.items():
        if info["alias"] == target:
            if info["blocked"]:
                update.message.reply_text(f"⚠️ {target} محظور بالفعل.")
                return
            info["blocked"] = True
            save_users()
            update.message.reply_text(f"🚫 تم حظر {target}.")
            try:
                bot.send_message(int(uid), "⚠️ تم حظرك من الدردشة من قبل المشرف.")
            except:
                pass
            return
    update.message.reply_text("❌ Alias غير موجود.")

@admin_only
def cmd_unblock(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("Usage: /unblock ALIAS")
        return
    target = context.args[0]
    for uid, info in users_data.items():
        if info["alias"] == target:
            if not info["blocked"]:
                update.message.reply_text(f"⚠️ {target} ليس محظوراً.")
                return
            info["blocked"] = False
            save_users()
            update.message.reply_text(f"✅ تم مسح الحظر عن {target}.")
            try:
                bot.send_message(int(uid), "✅ تم رفع الحظر عنك ويمكنك الآن الدردشة.")
            except:
                pass
            return
    update.message.reply_text("❌ Alias غير موجود.")

@admin_only
def cmd_blocked(update: Update, context: CallbackContext):
    blocked_users = [
        f"{info['alias']} (ID: {uid})"
        for uid, info in users_data.items() if info["blocked"]
    ]
    if not blocked_users:
        update.message.reply_text("لا يوجد مستخدمون محظورون حالياً.")
        return
    update.message.reply_text("قائمة المستخدمين المحظورين:\n" + "\n".join(blocked_users))

@admin_only
def cmd_usersfile(update: Update, context: CallbackContext):
    lines = []
    for uid, info in users_data.items():
        status = "🚫 محظور" if info["blocked"] else "✅ مفعل"
        lines.append(f"{info['alias']} (ID: {uid}) - {status}")
    content = "\n".join(lines)
    filename = "users_list.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    with open(filename, "rb") as f:
        update.message.reply_document(f, filename=filename)

@admin_only
def cmd_updateusers(update: Update, context: CallbackContext):
    if save_users():
        try:
            with open(USERS_FILE, "rb") as f:
                update.message.reply_document(f, filename=USERS_FILE, caption="✅ تم حفظ users.json. قم بتحديث المستودع بهذا الملف.")
        except Exception as e:
            update.message.reply_text(f"❌ فشل إرسال users.json: {e}")
    else:
        update.message.reply_text("❌ فشل حفظ users.json. تحقق من السجلات.")

@admin_only
def cmd_changepassword(update: Update, context: CallbackContext):
    global ACCESS_PASSWORD
    if not context.args:
        os.environ["ACCESS_PASSWORD"] = ""
        ACCESS_PASSWORD = ""
        for uid, info in users_data.items():
            info["pwd_ok"] = True
            info["joined"] = True
            if int(uid) != OWNER_ID:
                try:
                    bot.send_message(int(uid), "🔓 تم إزالة كلمة المرور. يمكنك الآن الدردشة بدون كلمة مرور.")
                except:
                    pass
        save_users()
        update.message.reply_text("✅ تم إزالة كلمة المرور. الدردشة الآن بدون كلمة مرور.")
        return

    new_password = " ".join(context.args).strip()
    if not new_password:
        update.message.reply_text("❌ يجب إدخال كلمة مرور جديدة أو ترك الأمر فارغًا لإزالة كلمة المرور.")
        return
    os.environ["ACCESS_PASSWORD"] = new_password
    ACCESS_PASSWORD = new_password
    for uid, info in users_data.items():
        if int(uid) != OWNER_ID:
            info["pwd_ok"] = False
            info["joined"] = False
            try:
                bot.send_message(int(uid), "🔒 تم تغيير كلمة المرور. أرسل كلمة المرور الجديدة للانضمام.")
            except:
                pass
        else:
            info["pwd_ok"] = True
            info["joined"] = True
    save_users()
    update.message.reply_text(f"✅ تم تغيير كلمة المرور إلى: {new_password}")

# ───── Webhook support ──────────────────────
@app.route("/", methods=["GET"])
def health_check():
    return "Bot en ligne", 200

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook_handler():
    if request.method == "POST":
        update = Update.de_json(request.get_json(force=True), bot)
        dispatcher.process_update(update)
        return "ok", 200
    return "Method Not Allowed", 405

def set_webhook():
    if WEBHOOK_URL:
        webhook_url = f"{WEBHOOK_URL}/{TOKEN}"
        bot.set_webhook(webhook_url)
        logger.info(f"Webhook set to {webhook_url}")
        logger.info("Bot en ligne")
        bot.send_message(OWNER_ID, "✅ Bot en ligne")
    else:
        logger.error("WEBHOOK_URL غير محدد في متغيرات البيئة.")

def delete_webhook():
    bot.delete_webhook()
    logger.info("Webhook deleted.")

# ───── تسجيل الأوامر ──────────────────────────────────────
dispatcher.add_handler(CommandHandler("start", cmd_start))
dispatcher.add_handler(CommandHandler("block", cmd_block))
dispatcher.add_handler(CommandHandler("unblock", cmd_unblock))
dispatcher.add_handler(CommandHandler("blocked", cmd_blocked))
dispatcher.add_handler(CommandHandler("usersfile", cmd_usersfile))
dispatcher.add_handler(CommandHandler("updateusers", cmd_updateusers))
dispatcher.add_handler(CommandHandler("changepassword", cmd_changepassword))

dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))
dispatcher.add_handler(MessageHandler(Filters.sticker, handle_sticker))
dispatcher.add_handler(MessageHandler(Filters.photo, handle_photo))
dispatcher.add_handler(MessageHandler(Filters.video, handle_video))
dispatcher.add_handler(MessageHandler(Filters.audio, handle_audio))
dispatcher.add_handler(MessageHandler(Filters.document, handle_document))

# ───── Main ─────────────────────────────────────────────
if __name__ == "__main__":
    if USE_WEBHOOK:
        set_webhook()
        logger.info("Starting Flask server...")
        app.run(host="0.0.0.0", port=PORT, debug=False)
    else:
        delete_webhook()
        logger.info("Starting polling...")
        updater.start_polling()
        updater.idle()
