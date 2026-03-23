import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

def dummy_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
    server = HTTPServer(("0.0.0.0", 10000), Handler)
    server.serve_forever()

threading.Thread(target=dummy_server, daemon=True).start()
# bot.py
import os
import re
import imaplib
import email
from email.header import decode_header
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from pymongo import MongoClient

# ----------------------------
# ENVIRONMENT VARIABLES
# ----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
IMAP_SERVER = "imap.gmail.com"

MONGO_URI = os.getenv("MONGO_URI")

# ----------------------------
# MONGODB SETUP
# ----------------------------
client = MongoClient(MONGO_URI)
db = client["telegram_bot"]
users_col = db["users"]
blocked_col = db["blocked"]
allowed_emails_col = db["allowed_emails"]

# ----------------------------
# DUMMY HTTP SERVER (Render free plan)
# ----------------------------
def dummy_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
    server = HTTPServer(("0.0.0.0", 10000), Handler)
    server.serve_forever()

# Start dummy server in a separate thread
threading.Thread(target=dummy_server, daemon=True).start()

# ----------------------------
# HELPER FUNCTIONS
# ----------------------------
async def is_blocked(user_id):
    return blocked_col.find_one({"user_id": user_id}) is not None

async def is_allowed_email(email_address):
    return allowed_emails_col.find_one({"email": email_address}) is not None

def extract_text_from_email(msg):
    text = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdispo = str(part.get("Content-Disposition"))
            if ctype == "text/plain" and "attachment" not in cdispo:
                text += part.get_payload(decode=True).decode(errors="ignore")
    else:
        text = msg.get_payload(decode=True).decode(errors="ignore")
    matches = re.findall(r"(Order\s*#?\d+|ID\s*:? ?\d+|Status\s*:? ?\w+|\d+)", text, re.IGNORECASE)
    return "\n".join(matches) if matches else "No extractable info found."

def get_latest_email(to_email):
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
        mail.select("inbox")
        status, messages = mail.search(None, "ALL")
        mail_ids = messages[0].split()
        for mail_id in reversed(mail_ids[-100:]):
            status, msg_data = mail.fetch(mail_id, "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    to_list = msg.get_all("To", []) + msg.get_all("Delivered-To", []) + msg.get_all("X-Original-To", [])
                    to_list = [decode_header(addr)[0][0].decode() if isinstance(decode_header(addr)[0][0], bytes) else decode_header(addr)[0][0] for addr in to_list]
                    if to_email in to_list:
                        return extract_text_from_email(msg)
        return "No email found for this address."
    except Exception as e:
        return f"Error accessing mailbox: {e}"

# ----------------------------
# TELEGRAM HANDLERS
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_blocked(update.effective_user.id):
        return
    await update.message.reply_text("Bot is running.")

async def latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if await is_blocked(user_id):
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /latest user@domain.com")
        return
    email_address = context.args[0]
    if not await is_allowed_email(email_address):
        await update.message.reply_text("No account found")
        return
    await update.message.reply_text("Searching latest email...")
    result = get_latest_email(email_address)
    await update.message.reply_text(result)

# ----------------------------
# ADMIN COMMANDS
# ----------------------------
async def users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    user_list = [str(u["user_id"]) for u in users_col.find()]
    await update.message.reply_text("Users:\n" + "\n".join(user_list) if user_list else "No users found.")

async def block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /block user_id")
        return
    blocked_col.insert_one({"user_id": int(context.args[0])})
    await update.message.reply_text(f"User {context.args[0]} blocked.")

async def unblock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /unblock user_id")
        return
    blocked_col.delete_one({"user_id": int(context.args[0])})
    await update.message.reply_text(f"User {context.args[0]} unblocked.")

async def addemail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /addemail email")
        return
    allowed_emails_col.insert_one({"email": context.args[0]})
    await update.message.reply_text(f"Email {context.args[0]} added.")

async def removeemail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /removeemail email")
        return
    allowed_emails_col.delete_one({"email": context.args[0]})
    await update.message.reply_text(f"Email {context.args[0]} removed.")

async def emails(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    email_list = [e["email"] for e in allowed_emails_col.find()]
    await update.message.reply_text("Allowed emails:\n" + "\n".join(email_list) if email_list else "No emails found.")

# ----------------------------
# MAIN FUNCTION
# ----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # User commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("latest", latest))

    # Admin commands
    app.add_handler(CommandHandler("users", users))
    app.add_handler(CommandHandler("block", block))
    app.add_handler(CommandHandler("unblock", unblock))
    app.add_handler(CommandHandler("addemail", addemail))
    app.add_handler(CommandHandler("removeemail", removeemail))
    app.add_handler(CommandHandler("emails", emails))

    # Run bot
    app.run_polling()

if __name__ == "__main__":
    main()
