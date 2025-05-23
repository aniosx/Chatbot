#!/usr/bin/env python

-- coding: utf-8 --

import os import json import random import time import logging from threading import Thread from flask import Flask, request, send_file from dotenv import load_dotenv from telegram import Update, Bot from telegram.ext import ( Updater, Dispatcher, CommandHandler, MessageHandler, Filters, CallbackContext )

─── Configuration & Logging ────────────────────────────────────────────────

load_dotenv() logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO) logger = logging.getLogger(name)

TOKEN = os.getenv("TELEGRAM_TOKEN") OWNER_ID = int(os.getenv("OWNER_ID", "0")) PORT = int(os.getenv("PORT", "8443")) ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD", "") USE_WEBHOOK = os.getenv("USE_WEBHOOK", "False").lower() == "true" WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")

─── Persistence ────────────────────────────────────────────────────────────

USERS_FILE = "users.json" if os.path.exists(USERS_FILE): with open(USERS_FILE, "r", encoding="utf-8") as f: users_data = json.load(f) else: users_data = {}

def save_users(): with open(USERS_FILE, "w", encoding="utf-8") as f: json.dump(users_data, f, ensure_ascii=False, indent=2)

def generate_alias(): return "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=4))

─── Rate limit & File size ─────────────────────────────────────────────────

MAX_MESSAGES_PER_MINUTE = 6 MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB message_timestamps = {}

def can_send(user_id): now = time.time() times = message_timestamps.get(user_id, []) times = [t for t in times if now - t < 60] if len(times) >= MAX_MESSAGES_PER_MINUTE: message_timestamps[user_id] = times return False times.append(now) message_timestamps[user_id] = times return True

─── Bot & Flask init ───────────────────────────────────────────────────────

bot = Bot(token=TOKEN) updater = Updater(token=TOKEN, use_context=True) dispatcher: Dispatcher = updater.dispatcher app = Flask(name)

─── Helpers ────────────────────────────────────────────────────────────────

def is_password_required(): return bool(ACCESS_PASSWORD.strip())

def welcome_text(uid): alias = users_data[uid]["alias"] if is_password_required() and not users_data[uid]["pwd_ok"]: return f"🔒 أرسل كلمة المرور للانضمام يا {alias}." return f"🚀 مرحباً {alias}! يمكنك الآن الدردشة."

def broadcast_to_others(sender_id, func): for uid, info in users_data.items(): if uid != sender_id and info["joined"] and not info["blocked"]: try: func(int(uid)) except Exception as e: logger.warning(f"Failed to send to {uid}: {e}")

─── Handlers ───────────────────────────────────────────────────────────────

def cmd_start(update: Update, context: CallbackContext): uid = str(update.effective_chat.id) if uid not in users_data: users_data[uid] = { "alias": generate_alias(), "blocked": False, "joined": False, "pwd_ok": not is_password_required(), "last_msgs": [] } save_users() update.message.reply_text(welcome_text(uid))

def handle_text(update: Update, context: CallbackContext): uid = str(update.effective_chat.id) text = update.message.text or "" if uid not in users_data: cmd_start(update, context) return user = users_data[uid] if user["blocked"]: update.message.reply_text("🚫 تم حظرك من استخدام البوت.") return if is_password_required() and not user["pwd_ok"]: if text.strip() == ACCESS_PASSWORD: user["pwd_ok"] = True user["joined"] = True save_users() update.message.reply_text("✅ تم قبول كلمة المرور. يمكنك الآن الدردشة.") else: update.message.reply_text("🔒 كلمة المرور خاطئة.") return if not user["joined"]: user["joined"] = True save_users() update.message.reply_text(f"✅ {user['alias']}، يمكنك الآن الدردشة.") return if not can_send(uid): update.message.reply_text("⚠️ تجاوزت الحد الأقصى للرسائل. انتظر قليلاً.") return alias = user["alias"] broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[{alias}] {text}"))

def handle_media(update: Update, context: CallbackContext, media_type): uid = str(update.effective_chat.id) user = users_data.get(uid) if not user or user["blocked"] or not user["joined"]: return media = getattr(update.message, media_type) if media.file_size > MAX_FILE_SIZE: update.message.reply_text("❌ الملف أكبر من الحجم المسموح.") return fid = media.file_id alias = user["alias"] context.bot.send_message(chat_id=uid, text=f"تم إرسال {media_type} إلى الجميع.") broadcast_to_others(uid, lambda cid: context.bot.send_message(cid, f"[{alias}] أرسل {media_type}:") ) send_func = getattr(context.bot, f"send_{media_type}") broadcast_to_others(uid, lambda cid: send_func(cid, **{media_type: fid}))

handle_sticker = lambda u, c: handle_media(u, c, "sticker") handle_photo = lambda u, c: handle_media(u, c, "photo") handle_video = lambda u, c: handle_media(u, c, "video") handle_document = lambda u, c: handle_media(u, c, "document") handle_audio = lambda u, c: handle_media(u, c, "audio")

─── Admin Commands ─────────────────────────────────────────────────────────

def admin_only(func): def wrapper(update: Update, context: CallbackContext): if update.effective_user.id != OWNER_ID: return return func(update, context) return wrapper

@admin_only def cmd_blocked(update: Update, context: CallbackContext): blocked = [f"{info['alias']} ({uid})" for uid, info in users_data.items() if info["blocked"]] update.message.reply_text("🚫 المحظورون:\n" + "\n".join(blocked) if blocked else "لا يوجد محظورون.")

@admin_only def cmd_block(update: Update, context: CallbackContext): if not context.args: return update.message.reply_text("Usage: /block ALIAS") target = context.args[0] for uid, info in users_data.items(): if info["alias"] == target: info["blocked"] = True save_users() context.bot.send_message(int(uid), "🚫 تم حظرك من استخدام البوت.") return update.message.reply_text(f"🚫 {target} تم حظره.") update.message.reply_text("❌ Alias غير موجود.")

@admin_only def cmd_unblock(update: Update, context: CallbackContext): if not context.args: return update.message.reply_text("Usage: /unblock ALIAS") target = context.args[0] for uid, info in users_data.items(): if info["alias"] == target: info["blocked"] = False save_users() context.bot.send_message(int(uid), "✅ تم مسح الحظر عنك.") return update.message.reply_text(f"✅ {target} تم مسح الحظر.") update.message.reply_text("❌ Alias غير موجود.")

@admin_only def cmd_usersfile(update: Update, context: CallbackContext): filename = "users_list.txt" with open(filename, "w", encoding="utf-8") as f: for uid, info in users_data.items(): f.write(f"{info['alias']} ({uid})\n") context.bot.send_document(update.effective_chat.id, document=open(filename, "rb"))

@admin_only def cmd_setpassword(update: Update, context: CallbackContext): global ACCESS_PASSWORD if not context.args: ACCESS_PASSWORD = "" update.message.reply_text("✅ تم حذف كلمة المرور.") else: ACCESS_PASSWORD = context.args[0] update.message.reply_text(f"✅ كلمة المرور أصبحت: {ACCESS_PASSWORD}") for u in users_data.values(): u["pwd_ok"] = not bool(ACCESS_PASSWORD) u["joined"] = u["pwd_ok"] save_users()

─── Register Handlers ──────────────────────────────────────────────────────

dispatcher.add_handler(CommandHandler("start", cmd_start)) dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text)) dispatcher.add_handler(MessageHandler(Filters.sticker, handle_sticker)) dispatcher.add_handler(MessageHandler(Filters.photo, handle_photo)) dispatcher.add_handler(MessageHandler(Filters.video, handle_video)) dispatcher.add_handler(MessageHandler(Filters.document, handle_document)) dispatcher.add_handler(MessageHandler(Filters.audio, handle_audio)) dispatcher.add_handler(CommandHandler("blocked", cmd_blocked)) dispatcher.add_handler(CommandHandler("block", cmd_block)) dispatcher.add_handler(CommandHandler("unblock", cmd_unblock)) dispatcher.add_handler(CommandHandler("usersfile", cmd_usersfile)) dispatcher.add_handler(CommandHandler("setpassword", cmd_setpassword))

─── Webhook vs Polling ─────────────────────────────────────────────────────

if USE_WEBHOOK: @app.route(f"/{TOKEN}", methods=["POST"]) def webhook_handler(): data = request.get_json(force=True) upd = Update.de_json(data, bot) dispatcher.process_update(upd) return "OK"

def main():
    bot.delete_webhook()
    bot.set_webhook(f"{WEBHOOK_URL}/{TOKEN}")
    logger.info(f"Webhook set to {WEBHOOK_URL}/{TOKEN}")
    app.run(host="0.0.0.0", port=PORT)

else: def main(): bot.delete_webhook() logger.info("Starting polling…") updater.start_polling() updater.idle()

if name == "main": main()

