#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import time
import logging
from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Updater, Dispatcher, CommandHandler, MessageHandler, Filters, CallbackContext
from collections import deque
from datetime import datetime, timedelta

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

# ───── حدود الرسائل والملفات ─────────────────────────
MAX_MESSAGES_PER_MINUTE = 5  # لكل مستخدم
MAX_BROADCAST_MESSAGES_PER_SECOND = 30  # إجمالي الرسائل المرسلة بين المستخدمين
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 ميجابايت

message_timestamps = {}  # user_id -> [timestamps] لحد الرسائل الفردية
broadcast_timestamps = deque()  # لحد الرسائل المرسلة بين المستخدمين
password_verified = set([OWNER_ID])  # تخزين مؤقت للمستخدمين الذين أدخلوا كلمة المرور

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

def can_broadcast():
    now = datetime.now()
    while broadcast_timestamps and now - broadcast_timestamps[0] > timedelta(seconds=1):
        broadcast_timestamps.popleft()
    if len(broadcast_timestamps) >= MAX_BROADCAST_MESSAGES_PER_SECOND:
        return False
    broadcast_timestamps.append(now)
    return True

# ───── قائمة المستخدمين المحظورين في الذاكرة ────────
blocked_users = set()

# ───── إعداد البوت والفلاسك ───────────────────────────
bot = Bot(token=TOKEN)
updater = Updater(token=TOKEN, use_context=True)
dispatcher: Dispatcher = updater.dispatcher
app = Flask(__name__)

# ───── وظائف مساعدة ───────────────────────────────────
def is_admin(user_id):
    return user_id == OWNER_ID

def is_password_required():
    return bool(ACCESS_PASSWORD)

def broadcast_to_others(sender_id, func):
    if not can_broadcast():
        logger.warning("Broadcast limit reached: 30 messages per second")
        return False
    success = False
    try:
        func(OWNER_ID)  # إرسال إلى المشرف كمثال (يمكن تعديله لمجموعة)
        success = True
        time.sleep(0.033)  # تأخير 33 مللي ثانية
    except Exception as e:
        logger.warning(f"Failed to broadcast to {OWNER_ID}: {e}")
    return success

# ───── الأوامر الأساسية ───────────────────────────────
def cmd_start(update: Update, context: CallbackContext):
    uid = update.effective_chat.id
    if uid in blocked_users:
        update.message.reply_text("⚠️ أنت محظور ولا يمكنك استخدام البوت.")
        return
    if not is_password_required() or uid in password_verified:
        update.message.reply_text("🚀 مرحبًا! يمكنك الآن الدردشة.")
        return
    update.message.reply_text("🔒 أرسل كلمة المرور للانضمام.")

def handle_text(update: Update, context: CallbackContext):
    uid = update.effective_chat.id
    if uid in blocked_users:
        update.message.reply_text("⚠️ أنت محظور ولا يمكنك إرسال الرسائل.")
        return
    text = update.message.text or ""
    if is_password_required() and uid not in password_verified:
        if text.strip() == ACCESS_PASSWORD:
            password_verified.add(uid)
            update.message.reply_text("✅ تم قبول كلمة المرور. يمكنك الآن الدردشة.")
        else:
            update.message.reply_text("🔒 كلمة المرور خاطئة.")
        return
    if not can_send(uid):
        update.message.reply_text("⚠️ تجاوزت 5 رسائل في الدقيقة. انتظر قليلاً.")
        return
    alias = f"User{uid}"
    broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[{alias}] {text}"))

def handle_sticker(update: Update, context: CallbackContext):
    uid = update.effective_chat.id
    if uid in blocked_users:
        update.message.reply_text("⚠️ أنت محظور ولا يمكنك إرسال الرسائل.")
        return
    if is_password_required() and uid not in password_verified:
        update.message.reply_text("🔒 أرسل كلمة المرور أولاً.")
        return
    if not can_send(uid):
        update.message.reply_text("⚠️ تجاوزت 5 رسائل في الدقيقة. انتظر قليلاً.")
        return
    sid = update.message.sticker.file_id
    alias = f"User{uid}"
    broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[{alias}] أرسل ستيكر:"))
    broadcast_to_others(uid, lambda cid: context.bot.send_sticker(cid, sticker=sid))

def handle_photo(update: Update, context: CallbackContext):
    uid = update.effective_chat.id
    if uid in blocked_users:
        update.message.reply_text("⚠️ أنت محظور ولا يمكنك إرسال الرسائل.")
        return
    if is_password_required() and uid not in password_verified:
        update.message.reply_text("🔒 أرسل كلمة المرور أولاً.")
        return
    if not can_send(uid):
        update.message.reply_text("⚠️ تجاوزت 5 رسائل في الدقيقة. انتظر قليلاً.")
        return
    photo = update.message.photo[-1]
    if photo.file_size > MAX_FILE_SIZE:
        update.message.reply_text("❌ الصورة أكبر من 50 ميجابايت.")
        return
    fid = photo.file_id
    alias = f"User{uid}"
    broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[{alias}] أرسل صورة:"))
    broadcast_to_others(uid, lambda cid: context.bot.send_photo(cid, photo=fid))

def handle_video(update: Update, context: CallbackContext):
    uid = update.effective_chat.id
    if uid in blocked_users:
        update.message.reply_text("⚠️ أنت محظور ولا يمكنك إرسال الرسائل.")
        return
    if is_password_required() and uid not in password_verified:
        update.message.reply_text("🔒 أرسل كلمة المرور أولاً.")
        return
    if not can_send(uid):
        update.message.reply_text("⚠️ تجاوزت 5 رسائل في الدقيقة. انتظر قليلاً.")
        return
    video = update.message.video
    if video.file_size > MAX_FILE_SIZE:
        update.message.reply_text("❌ الفيديو أكبر من 50 ميجابايت.")
        return
    vid = video.file_id
    alias = f"User{uid}"
    broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[{alias}] أرسل فيديو:"))
    broadcast_to_others(uid, lambda cid: context.bot.send_video(cid, video=vid))

def handle_audio(update: Update, context: CallbackContext):
    uid = update.effective_chat.id
    if uid in blocked_users:
        update.message.reply_text("⚠️ أنت محظور ولا يمكنك إرسال الرسائل.")
        return
    if is_password_required() and uid not in password_verified:
        update.message.reply_text("🔒 أرسل كلمة المرور أولاً.")
        return
    if not can_send(uid):
        update.message.reply_text("⚠️ تجاوزت 5 رسائل في الدقيقة. انتظر قليلاً.")
        return
    audio = update.message.audio
    if audio.file_size > MAX_FILE_SIZE:
        update.message.reply_text("❌ الملف الصوتي أكبر من 50 ميجابايت.")
        return
    aid = audio.file_id
    alias = f"User{uid}"
    broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[{alias}] أرسل ملف صوتي:"))
    broadcast_to_others(uid, lambda cid: context.bot.send_audio(cid, audio=aid))

def handle_document(update: Update, context: CallbackContext):
    uid = update.effective_chat.id
    if uid in blocked_users:
        update.message.reply_text("⚠️ أنت محظور ولا يمكنك إرسال الرسائل.")
        return
    if is_password_required() and uid not in password_verified:
        update.message.reply_text("🔒 أرسل كلمة المرور أولاً.")
        return
    if not can_send(uid):
        update.message.reply_text("⚠️ تجاوزت 5 رسائل في الدقيقة. انتظر قليلاً.")
        return
    doc = update.message.document
    if doc.file_size > MAX_FILE_SIZE:
        update.message.reply_text("❌ الملف أكبر من 50 ميجابايت.")
        return
    did = doc.file_id
    alias = f"User{uid}"
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
        update.message.reply_text("الاستخدام: /block USER_ID")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        update.message.reply_text("❌ USER_ID يجب أن يكون رقمًا.")
        return
    if target_id in blocked_users:
        update.message.reply_text(f"⚠️ المستخدم {target_id} محظور بالفعل.")
        return
    blocked_users.add(target_id)
    password_verified.discard(target_id)  # إزالة التحقق من كلمة المرور إذا كان محظورًا
    update.message.reply_text(f"🚫 تم حظر المستخدم {target_id}.")
    try:
        bot.send_message(target_id, "⚠️ تم حظرك من الدردشة من قبل المشرف.")
    except:
        pass

@admin_only
def cmd_unblock(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("الاستخدام: /unblock USER_ID")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        update.message.reply_text("❌ USER_ID يجب أن يكون رقمًا.")
        return
    if target_id not in blocked_users:
        update.message.reply_text(f"⚠️ المستخدم {target_id} ليس محظوراً.")
        return
    blocked_users.remove(target_id)
    update.message.reply_text(f"✅ تم إلغاء حظر المستخدم {target_id}.")
    try:
        bot.send_message(target_id, "✅ تم رفع الحظر عنك ويمكنك الآن الدردشة.")
    except:
        pass

@admin_only
def cmd_blocked(update: Update, context: CallbackContext):
    if not blocked_users:
        update.message.reply_text("لا يوجد مستخدمون محظورون حالياً.")
        return
    blocked_list = "\n".join([str(uid) for uid in blocked_users])
    update.message.reply_text(f"قائمة المستخدمين المحظورين:\n{blocked_list}")

# ───── Webhook support ──────────────────────
@app.route("/", methods=["GET"])
def health_check():
    return "Bot is running", 200

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
        bot.send_message(OWNER_ID, "✅ Bot is running")
    else:
        logger.error("WEBHOOK_URL is not set in environment variables.")

def delete_webhook():
    bot.delete_webhook()
    logger.info("Webhook deleted.")

# ───── تسجيل الأوامر ──────────────────────────────────────
dispatcher.add_handler(CommandHandler("start", cmd_start))
dispatcher.add_handler(CommandHandler("block", cmd_block))
dispatcher.add_handler(CommandHandler("unblock", cmd_unblock))
dispatcher.add_handler(CommandHandler("blocked", cmd_blocked))
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
        logger.info("Starting server with Gunicorn (local fallback to Flask)...")
        app.run(host="0.0.0.0", port=PORT, debug=False)
    else:
        delete_webhook()
        logger.info("Starting polling...")
        updater.start_polling()
        updater.idle()
