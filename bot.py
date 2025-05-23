#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import json
import random
import time
import logging
from flask import Flask, request, send_file
from io import StringIO

from telegram import Update, Bot
from telegram.ext import (
    Updater, Dispatcher,
    CommandHandler, MessageHandler, Filters, CallbackContext
)

# ========== CONFIGURATION ==========

TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
PORT = int(os.getenv("PORT", "8443"))
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD", "")
USE_WEBHOOK = os.getenv("USE_WEBHOOK", "False").lower() == "true"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")

MAX_MESSAGES_PER_MINUTE = 5
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

# ========== LOGGING ==========

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== DATA FILES ==========

USERS_FILE = "users.json"
if os.path.exists(USERS_FILE):
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users_data = json.load(f)
else:
    users_data = {}

def save_users():
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users_data, f, ensure_ascii=False, indent=2)

# ========== HELPERS ==========

def generate_alias():
    return "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=4))

message_timestamps = {}  # user_id -> list of timestamps (for rate limiting)

def can_send(user_id):
    now = time.time()
    times = message_timestamps.get(user_id, [])
    # Clean old timestamps (older than 60 seconds)
    times = [t for t in times if now - t < 60]
    if len(times) >= MAX_MESSAGES_PER_MINUTE:
        message_timestamps[user_id] = times
        return False
    times.append(now)
    message_timestamps[user_id] = times
    return True

def is_password_required():
    return bool(ACCESS_PASSWORD.strip())

def broadcast_to_others(sender_id, func):
    for uid, info in users_data.items():
        if uid != sender_id and info.get("joined", False) and not info.get("blocked", False):
            try:
                func(int(uid))
            except Exception as e:
                logger.warning(f"Failed sending to {uid}: {e}")

# ========== FLASK APP SETUP ==========

app = Flask(__name__)

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook_handler():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)
    dispatcher.process_update(update)
    return "OK"

@app.route("/")
def index():
    return "Bot is running."

# ========== TELEGRAM BOT SETUP ==========

bot = Bot(token=TOKEN)
updater = Updater(token=TOKEN, use_context=True)
dispatcher: Dispatcher = updater.dispatcher

# ========== COMMANDS & HANDLERS ==========

def start(update: Update, context: CallbackContext):
    uid = str(update.effective_chat.id)
    if uid not in users_data:
        users_data[uid] = {
            "alias": generate_alias(),
            "blocked": False,
            "joined": False,
            "pwd_ok": not is_password_required(),
            "last_msgs": []
        }
        save_users()

    user = users_data[uid]
    if is_password_required() and not user["pwd_ok"]:
        update.message.reply_text(f"🔒 مرحباً {user['alias']}, أرسل كلمة المرور للانضمام.")
    else:
        user["joined"] = True
        save_users()
        update.message.reply_text(f"🚀 مرحباً {user['alias']}! يمكنك الآن الدردشة.")

def handle_text(update: Update, context: CallbackContext):
    uid = str(update.effective_chat.id)
    text = update.message.text or ""
    if uid not in users_data:
        start(update, context)
        return

    user = users_data[uid]

    # Check blocked
    if user.get("blocked", False):
        update.message.reply_text("⚠️ أنت محظور ولا يمكنك إرسال رسائل.")
        return

    # Check password
    if is_password_required() and not user.get("pwd_ok", False):
        if text.strip() == ACCESS_PASSWORD:
            user["pwd_ok"] = True
            user["joined"] = True
            save_users()
            update.message.reply_text("✅ تم قبول كلمة المرور. يمكنك الآن الدردشة.")
        else:
            update.message.reply_text("🔒 كلمة المرور خاطئة.")
        return

    if not user.get("joined", False):
        user["joined"] = True
        save_users()
        update.message.reply_text(f"✅ {user['alias']}، يمكنك الآن الدردشة.")
        return

    # Rate limit
    if not can_send(uid):
        update.message.reply_text("⚠️ تجاوزت 5 رسائل في الدقيقة. انتظر قليلاً.")
        return

    alias = user["alias"]
    broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[{alias}] {text}"))

def handle_sticker(update: Update, context: CallbackContext):
    uid = str(update.effective_chat.id)
    user = users_data.get(uid)
    if not user or user.get("blocked", False) or not user.get("joined", False):
        return
    sid = update.message.sticker.file_id
    alias = user["alias"]
    broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[{alias}] أرسل ستيكر:"))
    broadcast_to_others(uid, lambda cid: context.bot.send_sticker(cid, sticker=sid))

def handle_photo(update: Update, context: CallbackContext):
    uid = str(update.effective_chat.id)
    user = users_data.get(uid)
    if not user or user.get("blocked", False) or not user.get("joined", False):
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
    if not user or user.get("blocked", False) or not user.get("joined", False):
        return
    video = update.message.video
    if video.file_size > MAX_FILE_SIZE:
        update.message.reply_text("❌ الفيديو أكبر من 50 ميغابايت.")
        return
    vid = video.file_id
    alias = user["alias"]
    broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[{alias}] أرسل فيديو:"))
    broadcast_to_others(uid, lambda cid: context.bot.send_video(cid, video=vid))

def handle_document(update: Update, context: CallbackContext):
    uid = str(update.effective_chat.id)
    user = users_data.get(uid)
    if not user or user.get("blocked", False) or not user.get("joined", False):
        return
    doc = update.message.document
    if doc.file_size > MAX_FILE_SIZE:
        update.message.reply_text("❌ الملف أكبر من 50 ميغابايت.")
        return
    did = doc.file_id
    alias = user["alias"]
    broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[{alias}] أرسل ملف:"))
    broadcast_to_others(uid, lambda cid: context.bot.send_document(cid, document=did))

def handle_audio(update: Update, context: CallbackContext):
    uid = str(update.effective_chat.id)
    user = users_data.get(uid)
    if not user or user.get("blocked", False) or not user.get("joined", False):
        return
    audio = update.message.audio
    if audio.file_size > MAX_FILE_SIZE:
        update.message.reply_text("❌ الملف الصوتي أكبر من 50 ميغابايت.")
        return
    aid = audio.file_id
    alias = user["alias"]
    broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[{alias}] أرسل ملف صوتي:"))
    broadcast_to_others(uid, lambda cid: context.bot.send_audio(cid, audio=aid))

# ========== ADMIN COMMANDS ==========

def admin_only(func):
    def wrapper(update: Update, context: CallbackContext):
        if update.effective_user.id != OWNER_ID:
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
            if info.get("blocked", False):
                update.message.reply_text(f"⚠️ {target} محظور مسبقاً.")
                return
            info["blocked"] = True
            save_users()
            update.message.reply_text(f"🚫 تم حظر {target}.")
            try:
                bot.send_message(int(uid), "⚠️ لقد تم حظرك من الدردشة.")
            except Exception as e:
                logger.warning(f"Failed to notify user {uid} about block: {e}")
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
            if not info.get("blocked", False):
                update.message.reply_text(f"⚠️ {target} ليس محظوراً.")
                return
            info["blocked"] = False
            save_users()
            update.message.reply_text(f"✅ تم مسح الحظر عن {target}.")
            try:
                bot.send_message(int(uid), "✅ تم رفع الحظر عنك، يمكنك الآن الدردشة.")
            except Exception as e:
                logger.warning(f"Failed to notify user {uid} about unblock: {e}")
            return
    update.message.reply_text("❌ Alias غير موجود.")

@admin_only
def cmd_broadcast(update: Update, context: CallbackContext):
    text = " ".join(context.args)
    if not text:
        update.message.reply_text("Usage: /broadcast MESSAGE")
        return
    for uid, info in users_data.items():
        if info.get("joined", False) and not info.get("blocked", False):
            try:
                context.bot.send_message(int(uid), f"📣 {text}")
            except Exception as e:
                logger.warning(f"Failed to send broadcast to {uid}: {e}")
    update.message.reply_text("✅ تم الإرسال.")

@admin_only
def cmd_setpassword(update: Update, context: CallbackContext):
    global ACCESS_PASSWORD
    if not context.args:
        ACCESS_PASSWORD = ""
        update.message.reply_text("✅ تم حذف كلمة المرور.")
    else:
        ACCESS_PASSWORD = context.args[0]
        update.message.reply_text(f"✅ كلمة المرور أصبحت: {ACCESS_PASSWORD}")
    # Update pwd_ok flags for users
    for u in users_data.values():
        u["pwd_ok"] = not bool(ACCESS_PASSWORD)
        if u["pwd_ok"]:
            u["joined"] = True
    save_users()

@admin_only
def cmd_blocked(update: Update, context: CallbackContext):
    lines = []
    for uid, info in users_data.items():
        if info.get("blocked", False):
            lines.append(f"{info['alias']} ({uid})")
    if not lines:
        update.message.reply_text("🚫 لا يوجد مستخدمين محظورين حالياً.")
    else:
        update.message.reply_text("🚫 المستخدمون المحظورون:\n" + "\n".join(lines))

@admin_only
def cmd_usersfile(update: Update, context: CallbackContext):
    if not users_data:
        update.message.reply_text("🚫 لا يوجد مستخدمين.")
        return

    lines = []
    for uid, info in users_data.items():
        lines.append(f"Alias: {info['alias']}, UserID: {uid}, محظور: {'نعم' if info.get('blocked', False) else 'لا'}")

    file_content = "\n".join(lines)
    bio = StringIO()
    bio.write(file_content)
    bio.seek(0)

    update.message.reply_document(document=bio, filename="users_list.txt")

# ========== Replace /users command with /blocked list ==========

# No /users command added to dispatcher to disable it

# ========== Register Handlers ==========

dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), handle_text))
dispatcher.add_handler(MessageHandler(Filters.sticker, handle_sticker))
dispatcher.add_handler(MessageHandler(Filters.photo, handle_photo))
dispatcher.add_handler(MessageHandler(Filters.video, handle_video))
dispatcher.add_handler(MessageHandler(Filters.document, handle_document))
dispatcher.add_handler(MessageHandler(Filters.audio, handle_audio))

# Admin commands
dispatcher.add_handler(CommandHandler("block", cmd_block))
dispatcher.add_handler(CommandHandler("unblock", cmd_unblock))
dispatcher.add_handler(CommandHandler("broadcast", cmd_broadcast))
dispatcher.add_handler(CommandHandler("setpassword", cmd_setpassword))
dispatcher.add_handler(CommandHandler("blocked", cmd_blocked))
dispatcher.add_handler(CommandHandler("usersfile", cmd_usersfile))

# ========== RUN BOT ==========

def main():
    if USE_WEBHOOK and WEBHOOK_URL:
        # Remove previous webhook
        bot.delete_webhook()
        bot.set_webhook(f"{WEBHOOK_URL}/{TOKEN}")
        logger.info("Webhook set: %s/%s", WEBHOOK_URL, TOKEN)
        app.run(host="0.0.0.0", port=PORT)
    else:
        updater.start_polling()
        updater.idle()

if __name__ == "__main__":
