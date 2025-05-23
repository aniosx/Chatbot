import os import json import random from flask import Flask, request from telegram import Update, Bot, File from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, Dispatcher

TOKEN = os.getenv("BOT_TOKEN") PASSWORD = os.getenv("PASSWORD", "") PORT = int(os.environ.get("PORT", 8443)) URL = os.getenv("RENDER_EXTERNAL_URL") or f"https://your-render-subdomain.onrender.com"

users_file = "users.json" state_file = "state.json"

if not os.path.exists(users_file): with open(users_file, "w") as f: json.dump({}, f)

if not os.path.exists(state_file): with open(state_file, "w") as f: json.dump({"password": PASSWORD}, f)

def load_users(): with open(users_file, "r") as f: return json.load(f)

def save_users(users): with open(users_file, "w") as f: json.dump(users, f)

def load_state(): with open(state_file, "r") as f: return json.load(f)

def save_state(state): with open(state_file, "w") as f: json.dump(state, f)

bot = Bot(TOKEN) app = Flask(name) updater = Updater(token=TOKEN, use_context=True) dispatcher: Dispatcher = updater.dispatcher

Command: /start

def cmd_start(update: Update, context: CallbackContext): user_id = str(update.effective_user.id) users = load_users() if user_id not in users: users[user_id] = { "blocked": False, "name": f"User{random.randint(1000,9999)}", } save_users(users) context.bot.send_message(chat_id=update.effective_chat.id, text="أهلا بك في البوت")

Command: /setpassword

def cmd_setpassword(update: Update, context: CallbackContext): if not context.args: update.message.reply_text("يرجى إدخال كلمة السر الجديدة") return new_pw = context.args[0] state = load_state() state["password"] = new_pw save_state(state) update.message.reply_text("تم تغيير كلمة السر بنجاح")

Command: /block <id>

def cmd_block(update: Update, context: CallbackContext): if not context.args: update.message.reply_text("يرجى تحديد ID المستخدم") return uid = context.args[0] users = load_users() if uid in users: users[uid]["blocked"] = True save_users(users) update.message.reply_text("تم حظر المستخدم")

Command: /unblock <id>

def cmd_unblock(update: Update, context: CallbackContext): if not context.args: update.message.reply_text("يرجى تحديد ID المستخدم") return uid = context.args[0] users = load_users() if uid in users: users[uid]["blocked"] = False save_users(users) update.message.reply_text("تم مسح الحظر عن المستخدم")

Command: /blocked

def cmd_blocked(update: Update, context: CallbackContext): users = load_users() text = "قائمة المحظورين:\n" for uid, data in users.items(): if data.get("blocked"): text += f"- {data['name']} (ID: {uid})\n" update.message.reply_text(text or "لا يوجد مستخدمون محظورون")

Command: /usersfile

def cmd_usersfile(update: Update, context: CallbackContext): users = load_users() text = "قائمة المستخدمين:\n" for uid, data in users.items(): text += f"- {data['name']} (ID: {uid})\n" with open("users_list.txt", "w") as f: f.write(text) update.message.reply_document(document=open("users_list.txt", "rb"))

Message handler

def handle_message(update: Update, context: CallbackContext): user_id = str(update.effective_user.id) users = load_users() if user_id in users and users[user_id].get("blocked"): context.bot.send_message(chat_id=update.effective_chat.id, text="تم حظرك من استخدام البوت.") return # relay message to admin or handle anonymous logic context.bot.send_message(chat_id=update.effective_chat.id, text="تم إرسال رسالتك")

Handlers

dispatcher.add_handler(CommandHandler("start", cmd_start)) dispatcher.add_handler(CommandHandler("setpassword", cmd_setpassword)) dispatcher.add_handler(CommandHandler("block", cmd_block)) dispatcher.add_handler(CommandHandler("unblock", cmd_unblock)) dispatcher.add_handler(CommandHandler("blocked", cmd_blocked)) dispatcher.add_handler(CommandHandler("usersfile", cmd_usersfile)) dispatcher.add_handler(MessageHandler(Filters.text | Filters.document | Filters.video | Filters.audio, handle_message))

Webhook route

@app.route(f"/{TOKEN}", methods=["POST"]) def webhook(): update = Update.de_json(request.get_json(force=True), bot) dispatcher.process_update(update) return "ok"

Set webhook on startup

@app.before_first_request def set_webhook(): bot.set_webhook(f"{URL}/{TOKEN}")

Run flask app

if name == "main": app.run(host="0.0.0.0", port=PORT)

