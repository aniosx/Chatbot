#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import time
import logging
import json
import threading
from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Updater, Dispatcher, CommandHandler, MessageHandler, Filters, CallbackContext
from collections import deque
from datetime import datetime, timedelta
import random

# ───── إعدادات أساسية ────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.DEBUG
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
USE_WEBHOOK = os.getenv("USE_WEBHOOK", "False").lower() == "true"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
PORT = int(os.getenv("PORT", "8443"))
ACTIVE_USERS_FILE = "active_users.json"  # ملف لتخزين المستخدمين النشطين

# ───── حدود الرسائل والملفات ─────────────────────────
MAX_MESSAGES_PER_MINUTE = 5  # لكل مستخدم
MAX_BROADCAST_MESSAGES_PER_SECOND = 30  # إجمالي الرسائل المرسلة بين المستخدمين
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 ميجابايت

message_timestamps = {}  # user_id -> [timestamps] لحد الرسائل الفردية
broadcast_timestamps = deque()  # لحد الرسائل المرسلة بين المستخدمين
active_users = set([OWNER_ID])  # تخزين مؤقت للمستخدمين النشطين
blocked_users = set()  # المستخدمون المحظورون
user_aliases = {}  # user_id -> alias لتخزين الأسماء المستعارة
file_lock = threading.Lock()  # قفل لتجنب الكتابة المتزامنة

# ───── وظائف لإدارة المستخدمين النشطين ───────────────
def load_active_users():
    """تحميل قائمة المستخدمين النشطين من ملف JSON"""
    global active_users
    try:
        with file_lock:
            with open(ACTIVE_USERS_FILE, "r") as f:
                active_ids = json.load(f)
                active_users.update(active_ids)
                logger.info(f"Loaded active users: {active_users}")
    except FileNotFoundError:
        logger.info("No active users file found, starting with OWNER_ID only")
        active_users.add(OWNER_ID)
    except Exception as e:
        logger.error(f"Error loading active users: {e}")

def save_active_users():
    """حفظ قائمة المستخدمين النشطين إلى ملف JSON"""
    try:
        with file_lock:
            # تحميل القائمة الحالية أولاً لتجنب الكتابة فوقها
            current_users = set()
            try:
                with open(ACTIVE_USERS_FILE, "r") as f:
                    current_users.update(json.load(f))
            except FileNotFoundError:
                pass
            # دمج القائمتين
            current_users.update(active_users)
            with open(ACTIVE_USERS_FILE, "w") as f:
                json.dump(list(current_users), f)
        logger.debug(f"Saved active users: {current_users}")
    except Exception as e:
        logger.error(f"Error saving active users: {e}")

# ───── وظائف مساعدة ───────────────────────────────────
def can_send(user_id):
    now = time.time()
    times = message_timestamps.get(user_id, [])
    times = [t for t in times if now - t < 60]
    if len(times) >= MAX_MESSAGES_PER_MINUTE:
        message_timestamps[user_id] = times
        logger.debug(f"User {user_id} exceeded message limit: {len(times)} messages in 60s")
        return False
    times.append(now)
    message_timestamps[user_id] = times
    return True

def can_broadcast():
    now = datetime.now()
    while broadcast_timestamps and now - broadcast_timestamps[0] > timedelta(seconds=1):
        broadcast_timestamps.popleft()
    if len(broadcast_timestamps) >= MAX_BROADCAST_MESSAGES_PER_SECOND:
        logger.warning(f"Broadcast limit reached: {len(broadcast_timestamps)} messages per second")
        return False
    broadcast_timestamps.append(now)
    return True

def is_admin(user_id):
    is_admin_user = user_id == OWNER_ID
    logger.debug(f"Checking admin status for user {user_id}: {'Admin' if is_admin_user else 'Not Admin'}")
    return is_admin_user

def get_user_display_name(user):
    """إرجاع اسم العرض بناءً على المستخدم"""
    if user.username:
        return f"@{user.username}"
    return user.first_name or f"User{user.id}"

def get_user_alias(user_id):
    """إرجاع اسم مستعار للمستخدم (بدون ID)"""
    if user_id not in user_aliases:
        user_aliases[user_id] = f"User{random.randint(1000, 9999)}"
        logger.debug(f"Generated alias for user {user_id}: {user_aliases[user_id]}")
    return user_aliases[user_id]

def broadcast_to_others(sender_id, func):
    if not can_broadcast():
        logger.warning("Broadcast limit reached, cannot send message")
        return False
    logger.debug(f"Broadcasting message from {sender_id} to {len(active_users)} active users")
    success = False
    for uid in active_users:
        if uid != sender_id and uid not in blocked_users:
            try:
                logger.debug(f"Sending message to user {uid}")
                func(uid)
                success = True
                time.sleep(0.033)  # تأخير 33 مللي ثانية لتجنب حظر Telegram
            except Exception as e:
                logger.error(f"Failed to broadcast to {uid}: {e}")
    if not success:
        logger.warning(f"No valid recipients for broadcast from {sender_id}. Active users: {active_users}, Blocked users: {blocked_users}")
    return success

# ───── إعداد البوت والفلاسك ───────────────────────────
bot = Bot(token=TOKEN)
updater = Updater(token=TOKEN, use_context=True)
dispatcher: Dispatcher = updater.dispatcher
app = Flask(__name__)

# ───── الأوامر الأساسية ───────────────────────────────
def cmd_start(update: Update, context: CallbackContext):
    uid = update.effective_chat.id
    logger.debug(f"Start command received from user {uid}")
    if uid in blocked_users:
        update.message.reply_text("⚠️ أنت محظور ولا يمكنك استخدام البوت.")
        return
    active_users.add(uid)
    save_active_users()
    logger.debug(f"User {uid} added to active users")
    update.message.reply_text("🚀 مرحبًا! يمكنك الآن الدردشة.")

def handle_text(update: Update, context: CallbackContext):
    uid = update.effective_chat.id
    logger.debug(f"Text message received from user {uid}: {update.message.text}")
    if uid in blocked_users:
        update.message.reply_text("⚠️ أنت محظور ولا يمكنك إرسال الرسائل.")
        return
    if not can_send(uid):
        update.message.reply_text("⚠️ تجاوزت 5 رسائل في الدقيقة. انتظر قليلاً.")
        return
    active_users.add(uid)
    save_active_users()
    alias = get_user_alias(uid)
    display_name = get_user_display_name(update.effective_user)
    
    if is_admin(uid):
        logger.debug(f"Admin {uid} sending message: {update.message.text}")
        broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[Boss] {update.message.text}"))
    else:
        logger.debug(f"User {uid} sending message with alias {alias}: {update.message.text}")
        broadcast_to_others(uid, lambda cid: context.bot.send_message(
            cid, f"[{alias}] {update.message.text}" if cid != OWNER_ID else f"[{display_name} | ID: {uid}] {update.message.text}"
        ))

def handle_sticker(update: Update, context: CallbackContext):
    uid = update.effective_chat.id
    logger.debug(f"Sticker received from user {uid}")
    if uid in blocked_users:
        update.message.reply_text("⚠️ أنت محظور ولا يمكنك إرسال الرسائل.")
        return
    if not can_send(uid):
        update.message.reply_text("⚠️ تجاوزت 5 رسائل في الدقيقة. انتظر قليلاً.")
        return
    active_users.add(uid)
    save_active_users()
    sid = update.message.sticker.file_id
    alias = get_user_alias(uid)
    display_name = get_user_display_name(update.effective_user)
    
    if is_admin(uid):
        broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[Boss] أرسل ستيكر:"))
        broadcast_to_others(uid, lambda cid: context.bot.send_sticker(cid, sticker=sid))
    else:
        broadcast_to_others(uid, lambda cid: context.bot.send_message(
            cid, f"[{alias}] أرسل ستيكر:" if cid != OWNER_ID else f"[{display_name} | ID: {uid}] أرسل ستيكر:"
        ))
        broadcast_to_others(uid, lambda cid: context.bot.send_sticker(cid, sticker=sid))

def handle_photo(update: Update, context: CallbackContext):
    uid = update.effective_chat.id
    logger.debug(f"Photo received from user {uid}")
    if uid in blocked_users:
        update.message.reply_text("⚠️ أنت محظور ولا يمكنك إرسال الرسائل.")
        return
    if not can_send(uid):
        update.message.reply_text("⚠️ تجاوزت 5 رسائل في الدقيقة. انتظر قليلاً.")
        return
    active_users.add(uid)
    save_active_users()
    photo = update.message.photo[-1]
    if photo.file_size > MAX_FILE_SIZE:
        update.message.reply_text("❌ الصورة أكبر من 50 ميجابايت.")
        return
    fid = photo.file_id
    alias = get_user_alias(uid)
    display_name = get_user_display_name(update.effective_user)
    
    if is_admin(uid):
        broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[Boss] أرسل صورة:"))
        broadcast_to_others(uid, lambda cid: context.bot.send_photo(cid, photo=fid))
    else:
        broadcast_to_others(uid, lambda cid: context.bot.send_message(
            cid, f"[{alias}] أرسل صورة:" if cid != OWNER_ID else f"[{display_name} | ID: {uid}] أرسل صورة:"
        ))
        broadcast_to_others(uid, lambda cid: context.bot.send_photo(cid, photo=fid))

def handle_video(update: Update, context: CallbackContext):
    uid = update.effective_chat.id
    logger.debug(f"Video received from user {uid}")
    if uid in blocked_users:
        update.message.reply_text("⚠️ أنت محظور ولا يمكنك إرسال الرسائل.")
        return
    if not can_send(uid):
        update.message.reply_text("⚠️ تجاوزت 5 رسائل في الدقيقة. انتظر قليلاً.")
        return
    active_users.add(uid)
    save_active_users()
    video = update.message.video
    if video.file_size > MAX_FILE_SIZE:
        update.message.reply_text("❌ الفيديو أكبر من 50 ميجابايت.")
        return
    vid = video.file_id
    alias = get_user_alias(uid)
    display_name = get_user_display_name(update.effective_user)
    
    if is_admin(uid):
        broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[Boss] أرسل فيديو:"))
        broadcast_to_others(uid, lambda cid: context.bot.send_video(cid, video=vid))
    else:
        broadcast_to_others(uid, lambda cid: context.bot.send_message(
            cid, f"[{alias}] أرسل فيديو:" if cid != OWNER_ID else f"[{display_name} | ID: {uid}] أرسل فيديو:"
        ))
        broadcast_to_others(uid, lambda cid: context.bot.send_video(cid, video=vid))

def handle_audio(update: Update, context: CallbackContext):
    uid = update.effective_chat.id
    logger.debug(f"Audio received from user {uid}")
    if uid in blocked_users:
        update.message.reply_text("⚠️ أنت محظور ولا يمكنك إرسال الرسائل.")
        return
    if not can_send(uid):
        update.message.reply_text("⚠️ تجاوزت 5 رسائل في الدقيقة. انتظر قليلاً.")
        return
    active_users.add(uid)
    save_active_users()
    audio = update.message.audio
    if audio.file_size > MAX_FILE_SIZE:
        update.message.reply_text("❌ الملف الصوتي أكبر من 50 ميجابايت.")
        return
    aid = audio.file_id
    alias = get_user_alias(uid)
    display_name = get_user_display_name(update.effective_user)
    
    if is_admin(uid):
        broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[Boss] أرسل ملف صوتي:"))
        broadcast_to_others(uid, lambda cid: context.bot.send_audio(cid, audio=aid))
    else:
        broadcast_to_others(uid, lambda cid: context.bot.send_message(
            cid, f"[{alias}] أرسل ملف صوتي:" if cid != OWNER_ID else f"[{display_name} | ID: {uid}] أرسل ملف صوتي:"
        ))
        broadcast_to_others(uid, lambda cid: context.bot.send_audio(cid, audio=aid))

def handle_document(update: Update, context: CallbackContext):
    uid = update.effective_chat.id
    logger.debug(f"Document received from user {uid}")
    if uid in blocked_users:
        update.message.reply_text("⚠️ أنت محظور ولا يمكنك إرسال الرسائل.")
        return
    if not can_send(uid):
        update.message.reply_text("⚠️ تجاوزت 5 رسائل في الدقيقة. انتظر قليلاً.")
        return
    active_users.add(uid)
    save_active_users()
    doc = update.message.document
    if doc.file_size > MAX_FILE_SIZE:
        update.message.reply_text("❌ الملف أكبر من 50 ميجابايت.")
        return
    did = doc.file_id
    alias = get_user_alias(uid)
    display_name = get_user_display_name(update.effective_user)
    
    if is_admin(uid):
        broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[Boss] أرسل ملف:"))
        broadcast_to_others(uid, lambda cid: context.bot.send_document(cid, document=did))
    else:
        broadcast_to_others(uid, lambda cid: context.bot.send_message(
            cid, f"[{alias}] أرسل ملف:" if cid != OWNER_ID else f"[{display_name} | ID: {uid}] أرسل ملف:"
        ))
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
    active_users.discard(target_id)
    save_active_users()
    logger.debug(f"User {target_id} blocked and removed from active users")
    update.message.reply_text(f"🚫 تم حظر المستخدم {target_id}.")
    try:
        bot.send_message(target_id, "⚠️ تم حظرك من الدردشة من قبل المشرف.")
    except Exception as e:
        logger.error(f"Failed to notify user {target_id} of block: {e}")

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
    except Exception as e:
        logger.error(f"Failed to notify user {target_id} of unblock: {e}")

@admin_only
def cmd_blocked(update: Update, context: CallbackContext):
    if not blocked_users:
        update.message.reply_text("لا يوجد مستخدمون محظورون حالياً.")
        return
    blocked_list = "\n".join([str(uid) for uid in blocked_users])
    update.message.reply_text(f"قائمة المستخدمين المحظورين:\n{blocked_list}")

@admin_only
def cmd_users(update: Update, context: CallbackContext):
    if not active_users:
        update.message.reply_text("لا يوجد مستخدمون نشطون حالياً.")
        return
    users_list = "\n".join([str(uid) for uid in active_users])
    update.message.reply_text(f"قائمة المستخدمين النشطين:\n{users_list}")

# ───── Webhook support ──────────────────────
@app.route("/", methods=["GET"])
def health_check():
    logger.debug("Health check endpoint accessed")
    return "Bot is running", 200

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook_handler():
    logger.debug("Webhook handler received POST request")
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
dispatcher.add_handler(CommandHandler("users", cmd_users))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))
dispatcher.add_handler(MessageHandler(Filters.sticker, handle_sticker))
dispatcher.add_handler(MessageHandler(Filters.photo, handle_photo))
dispatcher.add_handler(MessageHandler(Filters.video, handle_video))
dispatcher.add_handler(MessageHandler(Filters.audio, handle_audio))
dispatcher.add_handler(MessageHandler(Filters.document, handle_document))

# ───── Main ─────────────────────────────────────────────
if __name__ == "__main__":
    logger.info(f"Starting bot with OWNER_ID={OWNER_ID}, USE_WEBHOOK={USE_WEBHOOK}")
    load_active_users()  # تحميل المستخدمين النشطين عند بدء التشغيل
    if USE_WEBHOOK:
        set_webhook()
        logger.info("Starting server with Gunicorn (local fallback to Flask)...")
        app.run(host="0.0.0.0", port=PORT, debug=False)
    else:
        delete_webhook()
        logger.info("Starting polling...")
        updater.start_polling()
        updater.idle()
