#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import json
import random
import time
import logging
from flask import Flask, request
from dotenv import load_dotenv
from telegram import Update, Bot
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters, CallbackContext

# ─── إعداد ───────────────────────────────────────────────────────────────
load_dotenv()
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD", "")
USE_WEBHOOK = os.getenv("USE_WEBHOOK", "False").lower() == "true"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
PORT = int(os.environ.get("PORT", "10000"))

# ─── البيانات ───────────────────────────────────────────────────────────
USERS_FILE = "users.json"
if os.path.exists(USERS_FILE):
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users_data = json.load(f)
else:
    users_data = {}

def save_users():
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users_data, f, ensure_ascii=False, indent=2)

def generate_alias():
    return "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=4))

# ─── قيود الرسائل والملفات ─────────────────────────────────────────────────
MAX_MESSAGES_PER_MINUTE = 5
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
message_timestamps = {}

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

# ─── بوت ─────────────────────────────────────────────────────────────────
bot = Bot(token=TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot, None, workers=0)

# ─── مساعدات ────────────────────────────────────────────────────────────
def is_password_required():
    return bool(ACCESS_PASSWORD.strip())

def welcome_text(uid):
    alias = users_data[uid]["alias"]
    if is_password_required() and not users_data[uid]["pwd_ok"]:
        return f"🔒 أرسل كلمة المرور للانضمام يا {alias}."
    return f"🚀 مرحباً {alias}! يمكنك الآن الدردشة."

def broadcast_to_others(sender_id, func):
    for uid, info in users_data.items():
        if uid != sender_id and info["joined"] and not info["blocked"]:
            try:
                func(int(uid))
            except Exception as e:
                logger.warning(f"فشل الإرسال إلى {uid}: {e}")

# ─── المعالجون ───────────────────────────────────────────────────────────
def cmd_start(update: Update, context: CallbackContext):
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
    update.message.reply_text(welcome_text(uid))

def handle_text(update: Update, context: CallbackContext):
    uid = str(update.effective_chat.id)
    text = update.message.text or ""
    if uid not in users_data:
        cmd_start(update, context)
        return
    user = users_data[uid]
    if user["blocked"]:
        update.message.reply_text("🚫 لا يمكنك إرسال رسائل لأنك محظور.")
        return
    if is_password_required() and not user["pwd_ok"]:
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
    broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[{alias}] {text}"))

def handle_file(update: Update, context: CallbackContext):
    uid = str(update.effective_chat.id)
    user = users_data.get(uid)
    if not user or user["blocked"] or not user["joined"]:
        return
    msg = update.message
    alias = user["alias"]

    # تحديد نوع الملف ومعرفه
    if msg.sticker:
        fid = msg.sticker.file_id
        ftype = "ستيكر"
    elif msg.photo:
        fid = msg.photo[-1].file_id
        ftype = "صورة"
    elif msg.video:
        if msg.video.file_size > MAX_FILE_SIZE:
            return update.message.reply_text("❌ الملف أكبر من 50 ميغابايت.")
        fid = msg.video.file_id
        ftype = "فيديو"
    elif msg.audio:
        if msg.audio.file_size > MAX_FILE_SIZE:
            return update.message.reply_text("❌ الملف أكبر من 50 ميغابايت.")
        fid = msg.audio.file_id
        ftype = "ملف صوتي"
    elif msg.voice:
        if msg.voice.file_size > MAX_FILE_SIZE:
            return update.message.reply_text("❌ الملف أكبر من 50 ميغابايت.")
        fid = msg.voice.file_id
        ftype = "مذكرة صوتية"
    elif msg.document:
        if msg.document.file_size > MAX_FILE_SIZE:
            return update.message.reply_text("❌ الملف أكبر من 50 ميغابايت.")
        fid = msg.document.file_id
        ftype = "ملف"
    else:
        return update.message.reply_text("⚠️ نوع الملف غير مدعوم.")

    # بث الملف
    broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[{alias}] أرسل {ftype}:"))
    if msg.sticker:
        broadcast_to_others(uid, lambda cid: context.bot.send_sticker(cid, fid))
    elif msg.photo:
        broadcast_to_others(uid, lambda cid: context.bot.send_photo(cid, photo=fid))
    elif msg.video:
        broadcast_to_others(uid, lambda cid: context.bot.send_video(cid, video=fid))
    elif msg.audio:
        broadcast_to_others(uid, lambda cid: context.bot.send_audio(cid, audio=fid))
    elif msg.voice:
        broadcast_to_others(uid, lambda cid: context.bot.send_voice(cid, voice=fid))
    else:
        broadcast_to_others(uid, lambda cid: context.bot.send_document(cid, document=fid))

# ─── أوامر الإدارة ─────────────────────────────────────────────────────
def admin_only(func):
    def wrapper(update: Update, context: CallbackContext):
        if update.effective_user.id != OWNER_ID:
            return
        return func(update, context)
    return wrapper

@admin_only
def cmd_block(update: Update, context: CallbackContext):
    if not context.args:
        return update.message.reply_text("Usage: /block ALIAS")
    target = context.args[0]
    for uid, info in users_data.items():
        if info["alias"] == target:
            info["blocked"] = True
            save_users()
            context.bot.send_message(chat_id=int(uid), text="🚫 تم حظرك من استخدام البوت.")
            return update.message.reply_text(f"🚫 {target} محظور.")
    update.message.reply_text("❌ Alias غير موجود.")

@admin_only
def cmd_unblock(update: Update, context: CallbackContext):
    if not context.args:
        return update.message.reply_text("Usage: /unblock ALIAS")
    target = context.args[0]
    for uid, info in users_data.items():
        if info["alias"] == target:
            info["blocked"] = False
            save_users()
            context.bot.send_message(chat_id=int(uid), text="✅ تم رفع الحظر عنك.")
            return update.message.reply_text(f"✅ {target} مسح الحظر.")
    update.message.reply_text("❌ Alias غير موجود.")

@admin_only
def cmd_blocked(update: Update, context: CallbackContext):
    blocked_users = [f"{info['alias']} ({uid})" for uid, info in users_data.items() if info["blocked"]]
    if not blocked_users:
        return update.message.reply_text("لا يوجد مستخدمون محظورون.")
    return update.message.reply_text("🚫 قائمة المحظورين:
" + "
".join(blocked_users))

@admin_only
def cmd_export(update: Update, context: CallbackContext):
    lines = [f"{info['alias']} ({uid})" for uid, info in users_data.items()]
    with open("users_export.txt", "w", encoding="utf-8") as f:
        f.write("
".join(lines))
    with open("users_export.txt", "rb") as f:
        update.message.reply_document(document=f, filename="users_export.txt")

# ─── تسجيل المعالجين ───────────────────────────────────────────────────
dispatcher.add_handler(CommandHandler("start", cmd_start))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))
dispatcher.add_handler(MessageHandler(Filters.sticker | Filters.photo | Filters.video | Filters.audio | Filters.voice | Filters.document, handle_file))
dispatcher.add_handler(CommandHandler("block", cmd_block))
dispatcher.add_handler(CommandHandler("unblock", cmd_unblock))
dispatcher.add_handler(CommandHandler("blocked", cmd_blocked))
dispatcher.add_handler(CommandHandler("export", cmd_export))

# ─── Webhook فقط ────────────────────────────────────────────────────────
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook_handler():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)
    dispatcher.process_update(update)
    return "OK"

def main():
    bot.delete_webhook()
    bot.set_webhook(f"{WEBHOOK_URL}/{TOKEN}")
    logger.info(f"تم تفعيل Webhook على {WEBHOOK_URL}/{TOKEN}")
    app.run(host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
