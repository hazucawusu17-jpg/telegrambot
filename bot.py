import imaplib
import email
import re
from email.header import decode_header

from pymongo import MongoClient
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ================= CONFIG =================

import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

MONGO_URI = os.getenv("MONGO_URI")

# ==========================================

import os
from pymongo import MongoClient

# MongoDB
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["telegram_bot"]  # Database
users_col = db["users"]
blocked_col = db["blocked"]
allowed_emails_col = db["allowed_emails"]


# ========= UTILS =========

def is_admin(user_id):
    return user_id == ADMIN_ID


def is_blocked(user_id):
    return blocked_col.find_one({"user_id": user_id}) is not None


def add_user(user_id):
    if not users_col.find_one({"user_id": user_id}):
        users_col.insert_one({"user_id": user_id})


def is_email_allowed(email_addr):
    return emails_col.find_one({"email": email_addr.lower()}) is not None


def extract_text(msg):
    """Extract text from multipart email safely"""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                return part.get_payload(decode=True).decode(errors="ignore")
    else:
        return msg.get_payload(decode=True).decode(errors="ignore")
    return ""


def extract_safe_data(text):
    """Extract non-sensitive data only"""
    patterns = [
        r"order\s*id[:\s]*([A-Z0-9\-]+)",
        r"order\s*number[:\s]*([A-Z0-9\-]+)",
        r"tracking\s*id[:\s]*([A-Z0-9\-]+)",
        r"tracking\s*number[:\s]*([A-Z0-9\-]+)",
        r"reference[:\s]*([A-Z0-9\-]+)",
        r"status[:\s]*([a-zA-Z ]+)",
    ]

    results = []

    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        results.extend(matches)

    return list(set(results))  # unique results


def match_recipient(msg, target_email):
    """Check if email was sent TO the target address"""
    headers = ["To", "Delivered-To", "X-Original-To"]

    for h in headers:
        val = msg.get(h, "")
        if target_email.lower() in val.lower():
            return True
    return False


def fetch_latest_email(target_email):
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
        mail.select("inbox")

        status, messages = mail.search(None, "ALL")
        email_ids = messages[0].split()

        # Limit to last 100 emails
        email_ids = email_ids[-100:]

        for eid in reversed(email_ids):
            res, msg_data = mail.fetch(eid, "(RFC822)")
            raw = msg_data[0][1]

            msg = email.message_from_bytes(raw)

            if match_recipient(msg, target_email):
                text = extract_text(msg)
                data = extract_safe_data(text)

                return data if data else ["No relevant data found"]

        return ["No matching email found"]

    except Exception as e:
        return [f"Error: {str(e)}"]


# ========= COMMANDS =========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    add_user(user_id)

    await update.message.reply_text("Bot is running.")


async def latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    add_user(user_id)

    if is_blocked(user_id):
        return await update.message.reply_text("You are blocked.")

    if not context.args:
        return await update.message.reply_text("Usage: /latest email@example.com")

    target_email = context.args[0].lower()

    if not is_email_allowed(target_email):
        return await update.message.reply_text("No account found")

    result = fetch_latest_email(target_email)

    await update.message.reply_text("\n".join(result))


# ========= ADMIN COMMANDS =========

async def users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    user_list = users_col.find()
    text = "\n".join(str(u["user_id"]) for u in user_list)

    await update.message.reply_text(text or "No users")


async def block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    uid = int(context.args[0])
    blocked_col.insert_one({"user_id": uid})

    await update.message.reply_text("Blocked")


async def unblock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    uid = int(context.args[0])
    blocked_col.delete_one({"user_id": uid})

    await update.message.reply_text("Unblocked")


async def add_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    email_addr = context.args[0].lower()
    emails_col.insert_one({"email": email_addr})

    await update.message.reply_text("Email added")


async def remove_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    email_addr = context.args[0].lower()
    emails_col.delete_one({"email": email_addr})

    await update.message.reply_text("Email removed")


async def list_emails(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    emails = emails_col.find()
    text = "\n".join(e["email"] for e in emails)

    await update.message.reply_text(text or "No emails")


# ========= MAIN =========

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("latest", latest))

    app.add_handler(CommandHandler("users", users))
    app.add_handler(CommandHandler("block", block))
    app.add_handler(CommandHandler("unblock", unblock))
    app.add_handler(CommandHandler("addemail", add_email))
    app.add_handler(CommandHandler("removeemail", remove_email))
    app.add_handler(CommandHandler("emails", list_emails))

    print("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()

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

threading.Thread(target=dummy_server).start()
