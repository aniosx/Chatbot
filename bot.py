#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import json
import random
import time
import logging
from threading import Thread

from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import (
    Updater, Dispatcher,
    CommandHandler, MessageHandler, Filters, CallbackContext
)

# ─── Configuration & Logging ────────────────────────────────────────────────
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s",
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Environment Variables ───────────────────────────────────────────────────
TOKEN           = os.getenv("TELEGRAM_TOKEN")
OWNER_ID        = int(os.getenv("OWNER_ID", "0"))
PORT            = int(os.getenv("PORT", "8443"))
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD", "").strip()
MODE            = os.getenv("MODE", "webhook")  # "webhook" or "polling"
WEBHOOK_URL     = os.getenv("WEBHOOK_URL", "").rstrip("/")

if not TOKEN or OWNER_ID == 0:
    logger.error("Please set TELEGRAM_TOKEN and OWNER_ID environment variables.")
    exit(1)

# ─── Persistence ────────────────────────────────────────────────────────────
USERS_FILE = "users.json"
STATE_FILE = "state.json"

# load or init users
if os.path.exists(USERS_FILE):
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users_data = json.load(f)
else:
    users_data = {}

# load or init state (password & blocked list)
if os.path.exists(STATE_FILE):
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)
else:
    state = {"password": ACCESS_PASSWORD, "blocked": []}

def save_users():
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users_data, f, ensure_ascii=False, indent=2)

def save_state():
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def generate_alias():
    return "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=4))

# ─── Rate limiting & File size ──────────────────────────────────────────────
MAX_MESSAGES_PER_MINUTE = 5
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

# ─── Bot & Flask Setup ──────────────────────────────────────────────────────
bot = Bot(token=TOKEN)
updater = Updater(token=TOKEN, use_context=True)
dispatcher: Dispatcher = updater.dispatcher
app = Flask(__name__)

# ─── Helpers ────────────────────────────────────────────────────────────────
def is_password_required():
    return bool(state.get("password"))

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

def admin_only(func):
    def wrapper(update: Update, context: CallbackContext):
        if update.effective_user.id != OWNER_ID:
            update.message.reply_text("🚫 ليس لديك صلاحية.")
            return
        return func(update, context)
    return wrapper

# ─── Command Handlers ───────────────────────────────────────────────────────
def cmd_start(update: Update, context: CallbackContext):
    uid = str(update.effective_chat.id)
    if uid not in users_data:
        users_data[uid] = {
            "alias": generate_alias(),
            "blocked": False,
            "joined": False,
            "pwd_ok": not is_password_required()
        }
        save_users()
    update.message.reply_text(welcome_text(uid))

@admin_only
def cmd_setpassword(update: Update, context: CallbackContext):
    if not context.args:
        state["password"] = ""
        save_state()
        update.message.reply_text("✅ تم مسح كلمة المرور.")
    else:
        state["password"] = context.args[0]
        save_state()
        update.message.reply_text(f"✅ كلمة المرور أصبحت: {state['password']}")
    # reset all users pwd_ok
    for u in users_data.values():
        u["pwd_ok"] = not bool(state["password"])
        u["joined"] = u["pwd_ok"]
    save_users()

@admin_only
def cmd_block(update: Update, context: CallbackContext):
    if not context.args: 
        update.message.reply_text("Usage: /block ALIAS")
        return
    target = context.args[0]
    for uid, info in users_data.items():
        if info["alias"] == target:
            info["blocked"] = True
            save_users()
            update.message.reply_text(f"🚫 تم حظر {target}.")
            try:
                bot.send_message(int(uid), "🚫 لقد تم حظرك.")
            except: pass
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
            info["blocked"] = False
            save_users()
            update.message.reply_text(f"✅ تم مسح الحظر عن {target}.")
            try:
                bot.send_message(int(uid), "✅ تم رفع الحظر عنك.")
            except: pass
            return
    update.message.reply_text("❌ Alias غير موجود.")

@admin_only
def cmd_blocked(update: Update, context: CallbackContext):
    lines = [f"{info['alias']} ({uid})" for uid, info in users_data.items() if info["blocked"]]
    update.message.reply_text("🚫 المحظورون:\n" + "\n".join(lines) if lines else "لا يوجد محظورون.")

@admin_only
def cmd_usersfile(update: Update, context: CallbackContext):
    lines = [f"{info['alias']} - {uid} - {'محظور' if info['blocked'] else 'مفعل'}"
             for uid, info in users_data.items()]
    content = "\n".join(lines)
    filename = "users_list.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    with open(filename, "rb") as f:
        update.message.reply_document(f, filename=filename)

# ─── Message & Media Handlers ───────────────────────────────────────────────
def handle_text(update: Update, context: CallbackContext):
    uid = str(update.effective_chat.id)
    text = update.message.text or ""
    if uid not in users_data:
        cmd_start(update, context); return
    user = users_data[uid]
    if user["blocked"]:
        update.message.reply_text("🚫 أنت محظور.")
        return
    if is_password_required() and not user["pwd_ok"]:
        if text == state["password"]:
            user["pwd_ok"] = True; user["joined"] = True; save_users()
            update.message.reply_text("✅ تم التحقق.")
        else:
            update.message.reply_text("🔒 كلمة المرور خاطئة.")
        return
    if not user["joined"]:
        user["joined"] = True; save_users()
        update.message.reply_text(f"✅ {user['alias']}، يمكنك الآن الدردشة."); return
    if not can_send(uid):
        update.message.reply_text("⚠️ معدل الرسائل مرتفع."); return
    alias=user["alias"]
    broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[{alias}] {text}"))

def handle_media(update: Update, context: CallbackContext):
    uid = str(update.effective_chat.id)
    user = users_data.get(uid)
    if not user or user["blocked"] or not user["joined"]: return
    msg = update.message
    fsize = 0
    file_id = None
    send_fn = None
    caption = f"[{user['alias']}] أرسل وسائط:"
    if msg.photo:
        file_id = msg.photo[-1].file_id; fsize=msg.photo[-1].file_size; send_fn=context.bot.send_photo
    elif msg.video:
        file_id = msg.video.file_id; fsize=msg.video.file_size; send_fn=context.bot.send_video
    elif msg.document:
        file_id = msg.document.file_id; fsize=msg.document.file_size; send_fn=context.bot.send_document
    elif msg.audio:
        file_id = msg.audio.file_id; fsize=msg.audio.file_size; send_fn=context.bot.send_audio
    else:
        return
    if fsize>MAX_FILE_SIZE:
        update.message.reply_text("❌ الملف أكبر من المسموح.")
        return
    broadcast_to_others(uid, lambda cid: send_fn(cid, file_id, caption=caption))

# ─── Register Handlers ──────────────────────────────────────────────────────
dispatcher.add_handler(CommandHandler("start", cmd_start))
dispatcher.add_handler(CommandHandler("setpassword", cmd_setpassword))
dispatcher.add_handler(CommandHandler("block", cmd_block))
dispatcher.add_handler(CommandHandler("unblock", cmd_unblock))
dispatcher.add_handler(CommandHandler("blocked", cmd_blocked))
dispatcher.add_handler(CommandHandler("usersfile", cmd_usersfile))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))
dispatcher.add_handler(MessageHandler(Filters.photo|Filters.video|Filters.document|Filters.audio, handle_media))

# ─── Run Bot ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if MODE == "webhook":
        updater.start_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TOKEN
        )
        updater.bot.set_webhook(f"{WEBHOOK_URL}/{TOKEN}")
        logger.info("Started in Webhook mode.")
    else:
        updater.start_polling()
        logger.info("Started in Polling mode.")
    updater.idle()
