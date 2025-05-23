#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import json
import random
import time
import logging
from threading import Thread
from io import BytesIO

from flask import Flask, request
from dotenv import load_dotenv
from telegram import Update, Bot, InputFile
from telegram.ext import (
    Updater, Dispatcher,
    CommandHandler, MessageHandler, Filters, CallbackContext
)

# ─── Configuration & Logging ────────────────────────────────────────────────

load_dotenv()
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s",
                    level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN            = os.getenv("TELEGRAM_TOKEN")
OWNER_ID         = int(os.getenv("OWNER_ID", "0"))
PORT             = int(os.getenv("PORT", "8443"))
ACCESS_PASSWORD  = os.getenv("ACCESS_PASSWORD", "")
USE_WEBHOOK      = os.getenv("USE_WEBHOOK", "False").lower() == "true"
WEBHOOK_URL      = os.getenv("WEBHOOK_URL", "").rstrip("/")

# ─── Persistence ────────────────────────────────────────────────────────────

USERS_FILE = "users.json"
if os.path.exists(USERS_FILE):
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users_data = json.load(f)
else:
    users_data = {}  # user_id -> {alias, blocked, joined, pwd_ok, last_msgs[]}

def save_users():
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users_data, f, ensure_ascii=False, indent=2)

def generate_alias():
    return "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=4))

# ─── Rate limit & File size ─────────────────────────────────────────────────

MAX_MESSAGES_PER_MINUTE = 5
# رفع الحد الأقصى لحجم الملفات حسب الحد المسموح به في بوتات تلغرام (50 ميغابايت)
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
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

# ─── Bot & Flask init ───────────────────────────────────────────────────────

bot = Bot(token=TOKEN)
updater = Updater(token=TOKEN, use_context=True)
dispatcher: Dispatcher = updater.dispatcher
app = Flask(__name__)

# ─── Helpers ────────────────────────────────────────────────────────────────

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
                logger.warning(f"Failed to send to {uid}: {e}")

# ─── Handlers ───────────────────────────────────────────────────────────────

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
        update.message.reply_text("❌ أنت محظور ولا يمكنك إرسال رسائل.")
        return

    # Password check
    if is_password_required() and not user["pwd_ok"]:
        if text.strip() == ACCESS_PASSWORD:
            user["pwd_ok"] = True
            user["joined"] = True
            save_users()
            update.message.reply_text("✅ تم قبول كلمة المرور. يمكنك الآن الدردشة.")
        else:
            update.message.reply_text("🔒 كلمة المرور خاطئة.")
        return

    # First join
    if not user["joined"]:
        user["joined"] = True
        save_users()
        update.message.reply_text(f"✅ {user['alias']}، يمكنك الآن الدردشة.")
        return

    # Rate limit
    if not can_send(uid):
        update.message.reply_text("⚠️ تجاوزت 5 رسائل في الدقيقة. انتظر قليلاً.")
        return

    # Broadcast text
    alias = user["alias"]
    broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[{alias}] {text}"))

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

# ─── Admin Commands ─────────────────────────────────────────────────────────

def admin_only(func):
    def wrapper(update: Update, context: CallbackContext):
        if update.effective_user.id != OWNER_ID:
            update.message.reply_text("❌ أنت لست المشرف.")
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
            if info["blocked"]:
                update.message.reply_text(f"⚠️ المستخدم {target} محظور مسبقاً.")
            else:
                info["blocked"] = True
                save_users()
                update.message.reply_text(f"🚫 {target} تم حظره.")
                try:
                    bot.send_message(int(uid), "❌ تم حظرك من الدردشة من قبل المشرف.")
                except:
                    pass
            return
    update.message.reply_text("❌ Alias غير موجود.")

@admin_only
def cmd_unblock(update: Update, context: CallbackContext):
    if not context.args:
        return update.message.reply_text("Usage: /unblock ALIAS")
    target = context.args[0]
    for uid, info in users_data.items():
        if info["alias"] == target:
            if not info["blocked"]:
                update.message.reply_text(f"⚠️ المستخدم {target} ليس محظوراً.")
            else:
                info["blocked"] = False
                save_users()
                update.message.reply_text(f"✅ {target} مسح الحظر.")
                try:
                    bot.send_message(int(uid), "✅ تم رفع الحظر عنك من قبل المشرف.")
                except:
                    pass
            return
    update.message.reply_text("❌ Alias غير موجود.")

@admin_only
def cmd_blocked(update: Update, context: CallbackContext):
    lines = []
    for uid, info in users_data.items():
        if info["blocked"]:
            lines.append(f"{info['alias']} ({uid})")
    if not lines:
        update.message.reply_text("لا يوجد مستخدمون محظورون.")
    else:
        update.message.reply_text("🚫 المستخدمون المحظورون:\n" + "\n".join(lines))

@admin_only
def cmd_usersfile(update: Update, context: CallbackContext):
    lines = []
    for uid, info in users_data.items():
        lines.append(f"{info['alias']} ({uid}) - محظور: {'نعم' if info['blocked'] else 'لا'}")
    content = "\n".join(lines)
    bio = BytesIO()
    bio.write(content.encode("utf-8"))
    bio.seek(0)
    update.message.reply_document(document=InputFile(bio, filename="users_list.txt"),
                                 caption="قائمة المستخدمين مع المعرفات والحالة")

@admin_only
def cmd_broadcast(update: Update, context: CallbackContext):
    text = " ".join(context.args)
    if not text:
        return update.message.reply_text("Usage: /broadcast MESSAGE")
    for uid, info in users_data.items():
        if info["joined"] and not info["blocked"]:
            context.bot.send_message(int(uid), f"📣 {text}")
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
    for u in users_data.values():
        u["pwd_ok"] = not bool(ACCESS_PASSWORD)
        if u["pwd_ok"]:
            u["joined"] = True
    save_users()

# ─── Register Handlers ──────────────────────────────────────────────────────

dispatcher.add_handler(CommandHandler("start", cmd_start))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))
dispatcher.add_handler(MessageHandler(Filters.sticker, handle_sticker))
dispatcher.add_handler(MessageHandler(Filters.photo, handle_photo))
dispatcher.add_handler(MessageHandler(Filters.video, handle_video))
dispatcher.add_handler(MessageHandler(Filters.audio, handle_audio))
dispatcher.add_handler(MessageHandler(Filters.document, handle_document))
dispatcher.add_handler(CommandHandler("block", cmd_block))
dispatcher.add_handler(CommandHandler("unblock", cmd_unblock))
dispatcher.add_handler(CommandHandler("blocked", cmd_blocked))
dispatcher.add_handler(CommandHandler("usersfile", cmd_usersfile))
dispatcher.add_handler(CommandHandler("broadcast", cmd_broadcast))
dispatcher.add_handler(CommandHandler("setpassword", cmd_setpassword))

# ─── Webhook vs Polling ─────────────────────────────────────────────────────

if USE_WEBHOOK:
    @app.route(f"/{TOKEN}", methods=["POST"])
    def webhook_handler():
        data = request.get_json(force=True)
        upd = Update.de_json(data, bot)
        dispatcher.process_update(upd)
        return "OK"

    def main():
        bot.delete_webhook()
        bot.set_webhook(f"{WEBHOOK_URL}/{TOKEN}")
        logger.info(f"Webhook set to {WEBHOOK_URL}/{TOKEN}")
        app.run(host="0.0.0.0", port=PORT)

else:
    def main():
        bot.delete_webhook()
        logger.info("Starting polling…")
        updater
