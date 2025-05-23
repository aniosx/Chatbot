import os import json import random import logging from flask import Flask, request from telegram import Update, Bot, File from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, Dispatcher

Logging setup

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO) logger = logging.getLogger(name)

Load or initialize users data

if os.path.exists("users.json"): with open("users.json", "r") as f: users = json.load(f) else: users = {}

if os.path.exists("state.json"): with open("state.json", "r") as f: state = json.load(f) else: state = {"blocked": [], "admin_ids": [], "password": ""}

Save data

def save_users(): with open("users.json", "w") as f: json.dump(users, f)

def save_state(): with open("state.json", "w") as f: json.dump(state, f)

Create Bot

TOKEN = os.environ.get("BOT_TOKEN") PORT = int(os.environ.get("PORT", 5000)) MODE = os.environ.get("MODE", "webhook") bot = Bot(token=TOKEN)

Flask app for webhook

app = Flask(name)

@app.route(f"/{TOKEN}", methods=["POST"]) def webhook(): update = Update.de_json(request.get_json(force=True), bot) dispatcher.process_update(update) return "OK"

@app.route("/") def index(): return "Bot is running."

Generate random anonymous ID

def get_random_name(): return "User" + str(random.randint(1000, 9999))

Command handlers

def cmd_start(update: Update, context: CallbackContext): uid = str(update.effective_user.id) if uid not in users: users[uid] = { "name": get_random_name(), "blocked": False } save_users() update.message.reply_text("أهلاً بك في البوت. يمكنك إرسال رسائل وسيتم توصيلها للمجموعة.")

def cmd_help(update: Update, context: CallbackContext): update.message.reply_text("أرسل رسالتك هنا بشكل مجهول.")

def cmd_block(update: Update, context: CallbackContext): if update.effective_user.id not in state["admin_ids"]: return if context.args: uid = context.args[0] state["blocked"].append(uid) save_state() update.message.reply_text(f"تم حظر المستخدم {uid}.") try: bot.send_message(chat_id=int(uid), text="تم حظرك من استخدام البوت.") except: pass

def cmd_unblock(update: Update, context: CallbackContext): if update.effective_user.id not in state["admin_ids"]: return if context.args: uid = context.args[0] if uid in state["blocked"]: state["blocked"].remove(uid) save_state() update.message.reply_text(f"تم مسح الحظر عن المستخدم {uid}.") try: bot.send_message(chat_id=int(uid), text="تم رفع الحظر عنك ويمكنك استخدام البوت الآن.") except: pass

def cmd_blocked(update: Update, context: CallbackContext): if update.effective_user.id not in state["admin_ids"]: return txt = "قائمة المحظورين:\n" for uid in state["blocked"]: name = users.get(uid, {}).get("name", "مجهول") txt += f"{name} (ID: {uid})\n" update.message.reply_text(txt or "لا يوجد مستخدمون محظورون.")

def cmd_usersfile(update: Update, context: CallbackContext): if update.effective_user.id not in state["admin_ids"]: return lines = [f"{u['name']} - ID: {uid}" for uid, u in users.items()] with open("users_list.txt", "w") as f: f.write("\n".join(lines)) update.message.reply_document(document=open("users_list.txt", "rb"))

def cmd_setpassword(update: Update, context: CallbackContext): if update.effective_user.id not in state["admin_ids"]: return if context.args: state["password"] = context.args[0] save_state() update.message.reply_text("تم تغيير كلمة المرور.")

def cmd_resetpassword(update: Update, context: CallbackContext): if update.effective_user.id not in state["admin_ids"]: return state["password"] = "" save_state() update.message.reply_text("تم مسح كلمة المرور.")

Message handler

def handle_message(update: Update, context: CallbackContext): uid = str(update.effective_user.id) if uid in state["blocked"]: update.message.reply_text("تم حظرك من استخدام البوت.") return if uid not in users: update.message.reply_text("يرجى استخدام /start أولاً.") return

name = users[uid]["name"]
message = update.message

try:
    if message.text:
        bot.send_message(chat_id=os.environ.get("GROUP_ID"), text=f"{name}: {message.text}")
    elif message.photo:
        file = message.photo[-1].get_file()
        bot.send_photo(chat_id=os.environ.get("GROUP_ID"), photo=file.file_id, caption=f"{name} أرسل صورة")
    elif message.video:
        file = message.video.get_file()
        bot.send_video(chat_id=os.environ.get("GROUP_ID"), video=file.file_id, caption=f"{name} أرسل فيديو")
    elif message.audio:
        file = message.audio.get_file()
        bot.send_audio(chat_id=os.environ.get("GROUP_ID"), audio=file.file_id, caption=f"{name} أرسل مقطع صوتي")
    elif message.voice:
        file = message.voice.get_file()
        bot.send_voice(chat_id=os.environ.get("GROUP_ID"), voice=file.file_id, caption=f"{name} أرسل رسالة صوتية")
    else:
        update.message.reply_text("نوع الرسالة غير مدعوم.")
        return
    update.message.reply_text("تم إرسال رسالتك بنجاح.")
except Exception as e:
    logger.error(e)
    update.message.reply_text("حدث خطأ أثناء إرسال رسالتك.")

Dispatcher setup

updater = Updater(TOKEN, use_context=True) dispatcher = updater.dispatcher

dispatcher.add_handler(CommandHandler("start", cmd_start)) dispatcher.add_handler(CommandHandler("help", cmd_help)) dispatcher.add_handler(CommandHandler("block", cmd_block)) dispatcher.add_handler(CommandHandler("unblock", cmd_unblock)) dispatcher.add_handler(CommandHandler("blocked", cmd_blocked)) dispatcher.add_handler(CommandHandler("usersfile", cmd_usersfile)) dispatcher.add_handler(CommandHandler("setpassword", cmd_setpassword)) dispatcher.add_handler(CommandHandler("resetpassword", cmd_resetpassword)) dispatcher.add_handler(MessageHandler(Filters.all, handle_message))

Start bot

if name == 'main': if MODE == "webhook": updater.start_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN) updater.bot.set_webhook(url=f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}") else: updater.start_polling() updater.idle()

