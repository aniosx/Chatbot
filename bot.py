#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import json
import time
import random
import threading
import logging

from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import Updater, Dispatcher, CommandHandler, MessageHandler, Filters, CallbackContext

# ─── Configuration & Logging ────────────────────────────────────────────────

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN          = os.getenv("TELEGRAM_TOKEN")
OWNER_ID       = int(os.getenv("OWNER_ID", "0"))
PORT           = int(os.getenv("PORT", "8443"))
ACCESS_PASSWORD= os.getenv("ACCESS_PASSWORD", "")
USE_WEBHOOK    = os.getenv("USE_WEBHOOK", "False").lower() == "true"
WEBHOOK_URL    = os.getenv("WEBHOOK_URL", "").rstrip("/")

# ─── Fichiers & Données en mémoire ─────────────────────────────────────────

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

# ─── Initialisation Bot & Flask ────────────────────────────────────────────

bot = Bot(token=TOKEN)
updater = Updater(token=TOKEN, use_context=True)
dispatcher: Dispatcher = updater.dispatcher

app = Flask(__name__)

# ─── Handlers ────────────────────────────────────────────────────────────────

def cmd_start(update: Update, context: CallbackContext):
    chat_id = str(update.effective_chat.id)
    if chat_id not in users_data:
        users_data[chat_id] = {
            "alias": generate_alias(),
            "joined": False,
            "blocked": False,
            "pwd_ok": not bool(ACCESS_PASSWORD)
        }
        save_users()
    context.bot.send_message(chat_id=int(chat_id), text="أهلاً! أرسل رسالة للبدء.")

def handle_message(update: Update, context: CallbackContext):
    chat_id = str(update.effective_chat.id)
    text = update.message.text or ""

    # 1) Init user si nouveau
    if chat_id not in users_data:
        users_data[chat_id] = {
            "alias": generate_alias(),
            "joined": False,
            "blocked": False,
            "pwd_ok": not bool(ACCESS_PASSWORD)
        }
        save_users()

    user = users_data[chat_id]

    # 2) Password check
    if ACCESS_PASSWORD and not user["pwd_ok"]:
        if text.strip() == ACCESS_PASSWORD:
            user["pwd_ok"] = True
            user["joined"] = True
            save_users()
            return context.bot.send_message(chat_id=int(chat_id), text="✅ تم قبول كلمة المرور. يمكنك الآن الدردشة.")
        else:
            return context.bot.send_message(chat_id=int(chat_id), text="🔒 ادخل كلمة المرور للانضمام.")

    # 3) Blocage
    if user["blocked"]:
        return  # nada

    # 4) First join if needed
    if not user["joined"]:
        user["joined"] = True
        save_users()
        context.bot.send_message(chat_id=int(chat_id), text="🚀 مرحباً! أنت الآن في القاعة.")
        return

    # 5) Broadcast à tous
    alias = user["alias"]
    for uid, info in users_data.items():
        if uid != chat_id and info["joined"] and not info["blocked"]:
            try:
                context.bot.send_message(chat_id=int(uid), text=f"[{alias}] {text}")
            except Exception as e:
                logger.warning(f"Échec envoi à {uid}: {e}")

# ─── Commandes Admin ────────────────────────────────────────────────────────

def admin_only(func):
    def wrapper(update: Update, context: CallbackContext):
        if update.effective_user.id != OWNER_ID:
            return
        return func(update, context)
    return wrapper

@admin_only
def cmd_users(update: Update, context: CallbackContext):
    msg = "👥 مستخدمون:\n"
    for uid, info in users_data.items():
        status = "🚫" if info["blocked"] else "✅"
        msg += f"{info['alias']} ({uid}) {status}\n"
    update.message.reply_text(msg)

@admin_only
def cmd_block(update: Update, context: CallbackContext):
    if not context.args:
        return update.message.reply_text("Usage: /block ALIAS")
    target = context.args[0]
    for uid, info in users_data.items():
        if info["alias"] == target:
            info["blocked"] = True
            save_users()
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
            return update.message.reply_text(f"✅ {target} مبسوح الحظر.")
    update.message.reply_text("❌ Alias غير موجود.")

@admin_only
def cmd_broadcast(update: Update, context: CallbackContext):
    text = " ".join(context.args)
    if not text:
        return update.message.reply_text("Usage: /broadcast MESSAGE")
    for uid, info in users_data.items():
        if info["joined"] and not info["blocked"]:
            try:
                context.bot.send_message(chat_id=int(uid), text=f"🔔 {text}")
            except:
                pass
    update.message.reply_text("📣 تم الإرسال للجميع.")

# ─── Enregistrement des handlers ────────────────────────────────────────────

dispatcher.add_handler(CommandHandler("start", cmd_start))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

dispatcher.add_handler(CommandHandler("users",   cmd_users))
dispatcher.add_handler(CommandHandler("block",   cmd_block))
dispatcher.add_handler(CommandHandler("unblock", cmd_unblock))
dispatcher.add_handler(CommandHandler("broadcast", cmd_broadcast))

# ─── Webhook via Flask ──────────────────────────────────────────────────────

if USE_WEBHOOK:
    @app.route(f"/{TOKEN}", methods=["POST"])
    def webhook_handler():
        payload = request.get_json(force=True)
        update = Update.de_json(payload, bot)
        dispatcher.process_update(update)
        return "OK"

    def main():
        # delete any old webhook, then set new
        bot.delete_webhook()
        bot.set_webhook(url=f"{WEBHOOK_URL}/{TOKEN}")
        logger.info(f"Webhook set to {WEBHOOK_URL}/{TOKEN}")

        # run flask
        app.run(host="0.0.0.0", port=PORT)

# ─── Polling fallback ───────────────────────────────────────────────────────

else:
    def main():
        # delete webhook if exists
        bot.delete_webhook()
        logger.info("Starting polling mode…")
        updater.start_polling()
        updater.idle()

# ─── Exécution ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
