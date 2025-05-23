#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import json
import random
import time
import logging
from threading import Thread
from flask import Flask, request

from telegram import Bot, Update
from telegram.ext import Updater, Dispatcher, CommandHandler, MessageHandler, Filters, CallbackContext

# ─── Config & Logging ────────────────────────────────────────────────────────
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
PORT = int(os.getenv("PORT", "8443"))
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD", "").strip()
USE_WEBHOOK = os.getenv("USE_WEBHOOK", "False").lower() == "true"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")

if not TOKEN or OWNER_ID == 0:
    logger.error("يرجى تعيين TELEGRAM_TOKEN و OWNER_ID في المتغيرات البيئية.")
    exit(1)

# ─── Data files ───────────────────────────────────────────────────────────────

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

# ─── Rate limit & File limits ──────────────────────────────────────────────────

MAX_MESSAGES_PER_MINUTE = 5
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB max per Telegram limits

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

# ─── Bot & Flask ──────────────────────────────────────────────────────────────

bot = Bot(token=TOKEN)
updater = Updater(token=TOKEN, use_context=True)
dispatcher: Dispatcher = updater.dispatcher
app = Flask(__name__)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def is_password_required():
    return bool(ACCESS_PASSWORD)

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
            update.message.reply_text("🚫 ليس لديك صلاحية تنفيذ هذا الأمر.")
            return
        return func(update, context)
    return wrapper

# ─── Handlers ────────────────────────────────────────────────────────────────

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
        update.message.reply_text("⚠️ أنت محظور ولا يمكنك إرسال رسائل.")
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

@admin_only
def cmd_block(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("Usage: /block ALIAS")
        return
    target = context.args[0]
    for uid, info in users_data.items():
        if info["alias"] == target:
            if info["blocked"]:
                update.message.reply_text(f"⚠️ المستخدم {target} محظور مسبقاً.")
                return
            info["blocked"] = True
            save_users()
            update.message.reply_text(f"🚫 تم حظر {target}.")
            try:
                bot.send_message(int(uid), "⚠️ لقد تم حظرك من الدردشة.")
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
                update.message.reply_text(f"⚠️ المستخدم {target} ليس محظوراً.")
                return
            info["blocked"] = False
            save_users()
            update.message.reply_text(f"✅ تم مسح الحظر عن {target}.")
            try:
                bot.send_message(int(uid), "✅ تم رفع الحظر عنك. يمكنك الآن الدردشة.")
            except:
                pass
            return
    update.message.reply_text("❌ Alias غير موجود.")

@admin_only
def cmd_usersfile(update: Update, context: CallbackContext):
    content = "Alias - UserID - Blocked\n"
    for uid, info in users_data.items():
        content += f"{info['alias']} - {uid} - {'محظور' if info['blocked'] else 'غير محظور'}\n"
    filename = "users_list.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    with open(filename, "rb") as f:
        update.message.reply_document(f)

@admin_only
def cmd_setpassword(update: Update, context: CallbackContext):
    global ACCESS_PASSWORD
    if not context.args:
        ACCESS_PASSWORD = ""
        update.message.reply_text("✅ تم إزالة كلمة المرور. أي مستخدم يمكنه الانضمام الآن.")
        # احفظ في متغير بيئي أو ملف حسب حاجتك
        return
    ACCESS_PASSWORD = context.args[0]
    update.message.reply_text("✅ تم تعيين كلمة المرور الجديدة.")
    # احفظ في متغير بيئي أو ملف حسب حاجتك

@admin_only
def cmd_blocked(update: Update, context: CallbackContext):
    blocked_list = [f"{info['alias']} - {uid}" for uid, info in users_data.items() if info["blocked"]]
    if not blocked_list:
        update.message.reply_text("لا يوجد مستخدمون محظورون.")
    else:
        update.message.reply_text("المستخدمون المحظورون:\n" + "\n".join(blocked_list))

# ─── Command registration ─────────────────────────────────────────────────────

dispatcher.add_handler(CommandHandler("start", cmd_start))
dispatcher.add_handler(CommandHandler("block", cmd_block))
dispatcher.add_handler(CommandHandler("unblock", cmd_unblock))
dispatcher.add_handler(CommandHandler("usersfile", cmd_usersfile))
dispatcher.add_handler(CommandHandler("setpassword", cmd_set))
