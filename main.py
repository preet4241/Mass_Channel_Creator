import os
import random
import asyncio
import sqlite3
import logging
import re
import pytz
from threading import Thread
from flask import Flask
from datetime import datetime
from telethon import TelegramClient
from telethon.tl.functions.channels import CreateChannelRequest
from telethon.tl.functions.messages import UpdatePinnedMessageRequest, ExportChatInviteRequest
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Flask server setup
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

# Config
API_ID = os.getenv("api_id")
API_HASH = os.getenv("api_hash")
PHONE = os.getenv("num")
BOT_TOKEN = os.getenv("bot_token")

# Database setup
conn = sqlite3.connect('projects.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS projects 
                 (id INTEGER PRIMARY KEY, name TEXT, type TEXT, quantity INTEGER, 
                  folder TEXT, folder_id INTEGER, status TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS daily_stats (date TEXT PRIMARY KEY, count INTEGER DEFAULT 0)''')
conn.commit()

# States
WAIT_TYPE, WAIT_QUANTITY, WAIT_FOLDER, WAIT_OTP, WAIT_PASSWORD = range(5)

# Auth state storage
auth_sessions = {}

async def check_daily_limit():
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("SELECT count FROM daily_stats WHERE date=?", (today,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO daily_stats (date, count) VALUES (?, 0)", (today,))
        conn.commit()
        return 0
    return row[0]

async def update_daily_count(add):
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("UPDATE daily_stats SET count = count + ? WHERE date=?", (add, today))
    conn.commit()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("📢 Create Channel", callback_data='type_channel')],
                [InlineKeyboardButton("👥 Create Group", callback_data='type_group')],
                [InlineKeyboardButton("🔐 Login Account", callback_data='login_account')],
                [InlineKeyboardButton("📊 Status", callback_data='status')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('🤖 **Smart Manager Bot**\n\nChoose what to create or manage:', reply_markup=reply_markup, parse_mode='Markdown')
    return WAIT_TYPE

async def type_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'status':
        # ... existing status logic ...
        cursor.execute("SELECT * FROM projects ORDER BY created_at DESC LIMIT 10")
        projects = cursor.fetchall()
        if not projects:
            await query.edit_message_text('No projects yet!')
            return ConversationHandler.END
        
        text = "📋 **Projects Status**\n\n"
        for proj in projects:
            status = "✅ Complete" if proj[6] == 'complete' else "⏳ Processing"
            text += f"• {proj[1]} ({proj[2]}) - {proj[3]} - {status}\n"
        await query.edit_message_text(text, parse_mode='Markdown')
        return ConversationHandler.END

    if query.data == 'login_account':
        chat_id = update.effective_chat.id
        client = TelegramClient(f'session_{chat_id}', API_ID, API_HASH)
        auth_sessions[chat_id] = {'client': client, 'project_id': None, 'folder_name': None}
        
        try:
            await client.connect()
            if await client.is_user_authorized():
                keyboard = [[InlineKeyboardButton("Cancel", callback_data='cancel_auth')]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text("✅ Account is already logged in!", reply_markup=reply_markup)
                return WAIT_TYPE
            
            await client.send_code_request(PHONE)
            keyboard = [[InlineKeyboardButton("Cancel", callback_data='cancel_auth')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("📲 **Login with OTP**\n\nApne Telegram app se OTP dekh kar yahan daalo:", reply_markup=reply_markup)
            return WAIT_OTP
        except Exception as e:
            await query.edit_message_text(f"❌ Error: {str(e)}")
            return ConversationHandler.END

    context.user_data['project_type'] = 'channel' if 'channel' in query.data else 'group'
    await query.edit_message_text(f"How many {context.user_data['project_type']}s create karne hai? (Total Project Quantity)")
    return WAIT_QUANTITY

async def cancel_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    if chat_id in auth_sessions:
        client = auth_sessions[chat_id]['client']
        if client.is_connected():
            await client.disconnect()
        del auth_sessions[chat_id]
    await query.edit_message_text("❌ Authentication cancelled.")
    return ConversationHandler.END

async def get_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text)
        context.user_data['quantity'] = qty
        keyboard = [[InlineKeyboardButton("Skip Folder", callback_data='skip_folder')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text('Folder name batao (like Channel-A) ya skip karo:', reply_markup=reply_markup)
        return WAIT_FOLDER
    except ValueError:
        await update.message.reply_text('Valid number daal bhai!')
        return WAIT_QUANTITY

async def get_folder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    folder_name = "None"
    
    if query:
        await query.answer()
        folder_name = "None"
        await query.edit_message_text("Starting normal creation...")
    else:
        folder_name = update.message.text
        await update.message.reply_text(f"Starting creation in folder/prefix: {folder_name}...")

    project_name = f"{folder_name}" if folder_name != "None" else "Channel"
    
    cursor.execute("INSERT INTO projects (name, type, quantity, folder, status) VALUES (?, ?, ?, ?, ?)",
                  (project_name, context.user_data['project_type'], context.user_data['quantity'], 
                   folder_name, 'processing'))
    conn.commit()
    project_id = cursor.lastrowid

    # Handle Auth
    chat_id = update.effective_chat.id
    client = TelegramClient(f'session_{chat_id}', API_ID, API_HASH)
    auth_sessions[chat_id] = {
        'client': client,
        'project_id': project_id,
        'folder_name': folder_name
    }
    
    try:
        await client.connect()
        if not await client.is_user_authorized():
            # Generate the code request correctly
            await client.send_code_request(PHONE)
            msg = "📲 **OTP Sent!**\nApne Telegram app se OTP dekh kar yahan daalo:"
            if query: await query.message.reply_text(msg)
            else: await update.message.reply_text(msg)
            return WAIT_OTP
        
        # Already authorized, go straight to creation
        await update.effective_message.reply_text("✅ Account already logged in. Starting creation...")
        asyncio.create_task(run_creation_task(update, context, chat_id))
        return ConversationHandler.END
    except Exception as e:
        msg = f"❌ Error: {str(e)}"
        if query: await query.message.reply_text(msg)
        else: await update.message.reply_text(msg)
        if client.is_connected(): await client.disconnect()
        return ConversationHandler.END

async def otp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    otp = update.message.text.strip()
    session = auth_sessions.get(chat_id)
    
    if not session:
        await update.message.reply_text("Session expired. /start again.")
        return ConversationHandler.END
    
    client = session['client']
    try:
        await client.sign_in(PHONE, otp)
        await update.message.reply_text("✅ Login Successful! Creation start ho rahi hai...")
        asyncio.create_task(run_creation_task(update, context, chat_id))
        return ConversationHandler.END
    except SessionPasswordNeededError:
        await update.message.reply_text("🔐 **Two-Step Verification!**\nApna Password daalo:")
        return WAIT_PASSWORD
    except Exception as e:
        await update.message.reply_text(f"❌ OTP Error: {str(e)}\nSahi OTP daalo ya /start karo.")
        return WAIT_OTP

async def password_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    password = update.message.text.strip()
    session = auth_sessions.get(chat_id)
    
    if not session: return ConversationHandler.END
    
    client = session['client']
    try:
        await client.sign_in(password=password)
        await update.message.reply_text("✅ Password Accepted! Creation start ho rahi hai...")
        asyncio.create_task(run_creation_task(update, context, chat_id))
        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(f"❌ Password Error: {str(e)}\nSahi password daalo:")
        return WAIT_PASSWORD

async def run_creation_task(update, context, chat_id):
    session = auth_sessions.get(chat_id)
    if not session: return
    
    client = session['client']
    project_id = session['project_id']
    folder_name = session['folder_name']
    
    try:
        cursor.execute("SELECT * FROM projects WHERE id=?", (project_id,))
        proj = cursor.fetchone()
        total_qty = proj[3]
        p_type = proj[2]
        base_name = folder_name if folder_name != "None" else "Channel"
        
        existing_numbers = set()
        async for dialog in client.iter_dialogs():
            if dialog.name and dialog.name.startswith(base_name):
                match = re.search(rf"{re.escape(base_name)}(\d+)", dialog.name)
                if match: existing_numbers.add(int(match.group(1)))
        
        created_count = 0
        num = 1
        while created_count < total_qty:
            if await check_daily_limit() >= 100:
                await update.effective_message.reply_text(f"⏳ Daily limit (100) reached. Project {proj[1]} paused.")
                break

            if num in existing_numbers:
                num += 1
                continue

            try:
                title = f"{base_name}{num:03d}"
                result = await client(CreateChannelRequest(
                    title=title, about="Birth Certificate Services", megagroup=(p_type == 'group')
                ))
                channel = result.chats[0]
                await asyncio.sleep(2)
                
                invite_link = "None"
                try:
                    invite = await client(ExportChatInviteRequest(peer=channel))
                    invite_link = invite.link
                except Exception: pass

                tz = pytz.timezone('Asia/Kolkata')
                now = datetime.now(tz)
                p_label = "GROUP" if p_type == 'group' else "CHANNEL"
                cert_msg = f"**`{p_label} BIRTH CERTIFICATE`**\n-------------------\n\n1. **Age:** `{now.strftime('%d/%m/%Y %I:%M %p')}`\n2. **ID:** `-100{channel.id}`\n3. **Link:** {invite_link}"

                try:
                    if os.path.exists('birth_cert.jpg'):
                        await client.send_file(channel, 'birth_cert.jpg', caption=cert_msg)
                    else:
                        msg = await client.send_message(channel, cert_msg)
                    await client(UpdatePinnedMessageRequest(peer=channel, id=msg.id, pm_oneside=True))
                except Exception: pass

                created_count += 1
                await update_daily_count(1)
                num += 1
                await asyncio.sleep(random.randint(60, 180))
            except Exception as e:
                if isinstance(e, FloodWaitError):
                    await asyncio.sleep(e.seconds + 60)
                    continue
                num += 1
                continue

        cursor.execute("UPDATE projects SET status='complete' WHERE id=?", (project_id,))
        conn.commit()
        await update.effective_message.reply_text(f"✅ **Project Complete!** Created {created_count} {p_type}s.")
    finally:
        await client.disconnect()
        if chat_id in auth_sessions: del auth_sessions[chat_id]

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAIT_TYPE: [CallbackQueryHandler(type_handler),
                       CallbackQueryHandler(cancel_auth, pattern='^cancel_auth$')],
            WAIT_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_quantity)],
            WAIT_FOLDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_folder),
                         CallbackQueryHandler(get_folder, pattern='^skip_folder$')],
            WAIT_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, otp_handler),
                      CallbackQueryHandler(cancel_auth, pattern='^cancel_auth$')],
            WAIT_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, password_handler),
                           CallbackQueryHandler(cancel_auth, pattern='^cancel_auth$')]
        },
        fallbacks=[CommandHandler("start", start)]
    )
    
    app.add_handler(conv_handler)
    print("Bot started!")
    app.run_polling()

if __name__ == '__main__':
    # Start Flask in a separate thread
    Thread(target=run_flask, daemon=True).start()
    main()
