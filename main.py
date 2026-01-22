import asyncio
import sqlite3
import logging
import re
import os
import sys
import traceback
from datetime import datetime
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import CreateChannelRequest
from telethon.tl.functions.messages import UpdatePinnedMessageRequest, ExportChatInviteRequest
from telethon.tl.functions.folders import EditPeerFoldersRequest
from telethon.tl.types import InputFolderPeer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

from telethon.errors import FloodWaitError
import random

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

# Config
BOT_TOKEN = '8028312869:AAErsD7WmHHw11c2lL2Jdoj_DBU4bqRv_kQ'
DAILY_LIMIT = 50

# Database setup
try:
    conn = sqlite3.connect('projects.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS projects 
                     (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, type TEXT, quantity INTEGER, 
                      folder TEXT, folder_id INTEGER, status TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS project_details 
                     (id INTEGER PRIMARY KEY, project_id INTEGER, channel_name TEXT, 
                      channel_id INTEGER, invite_link TEXT, creation_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS daily_stats (user_id INTEGER, date TEXT, count INTEGER DEFAULT 0, PRIMARY KEY (user_id, date))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS credentials 
                     (user_id INTEGER PRIMARY KEY, api_id TEXT, api_hash TEXT, phone TEXT, session_str TEXT)''')
    conn.commit()
except sqlite3.Error as e:
    logger.error(f"Database error during setup: {e}")
    sys.exit(1)

# States
(MENU, WAIT_TYPE, WAIT_QUANTITY, WAIT_FOLDER, 
 LOGIN_API_ID, LOGIN_API_HASH, LOGIN_PHONE, LOGIN_OTP, LOGIN_PASSWORD, WAIT_DELAY) = range(10)

async def check_daily_limit(user_id):
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute("SELECT count FROM daily_stats WHERE user_id=? AND date=?", (user_id, today))
        row = cursor.fetchone()
        if not row:
            cursor.execute("INSERT INTO daily_stats (user_id, date, count) VALUES (?, ?, 0)", (user_id, today))
            conn.commit()
            return 0
        return row[0]
    except sqlite3.Error as e:
        logger.error(f"Error checking daily limit: {e}")
        return 0

async def update_daily_count(user_id, add):
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute("UPDATE daily_stats SET count = count + ? WHERE user_id=? AND date=?", (add, user_id, today))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Error updating daily count: {e}")

async def get_creds(user_id):
    try:
        cursor.execute("SELECT api_id, api_hash, phone, session_str FROM credentials WHERE user_id=?", (user_id,))
        return cursor.fetchone()
    except sqlite3.Error as e:
        logger.error(f"Error getting credentials: {e}")
        return None

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ An unexpected error occurred. Please try again later.",
            parse_mode='HTML'
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Add Project", callback_data='menu_add')],
        [InlineKeyboardButton("👤 My Account", callback_data='menu_account'),
         InlineKeyboardButton("📊 Status", callback_data='menu_status')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = '🤖 <b>Smart Manager Bot</b>\n\nChoose an option:'
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='HTML')
    return MENU

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'menu_add':
        user_id = update.effective_user.id
        creds = await get_creds(user_id)
        if not creds or not creds[3]:
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back_to_main')]]
            await query.edit_message_text("❌ <b>Login Required!</b>\n\nPlease login in <b>My Account</b> first.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
            return MENU
            
        keyboard = [
            [InlineKeyboardButton("📢 Create Channel", callback_data='type_channel'),
             InlineKeyboardButton("👥 Create Group", callback_data='type_group')],
            [InlineKeyboardButton("🔙 Back", callback_data='back_to_main')]
        ]
        await query.edit_message_text('Select what to create:', reply_markup=InlineKeyboardMarkup(keyboard))
        return WAIT_TYPE

    elif query.data == 'menu_status':
        user_id = update.effective_user.id
        cursor.execute("SELECT * FROM projects WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (user_id,))
        projects = cursor.fetchall()
        text = "📋 <b>Project Status Panel</b>\n\n"
        if not projects:
            text += "No projects found."
        else:
            for proj in projects:
                status_icon = "✅" if proj[7] == 'complete' else "⏳"
                text += f"{status_icon} <b>{proj[2]}</b> ({proj[3]})\n"
                text += f"   └ Status: {proj[7].capitalize()} | Qty: {proj[4]}\n"
                text += f"   └ Details: /details_{proj[0]}\n\n"
        
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back_to_main')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return MENU

    elif query.data == 'menu_account':
        user_id = update.effective_user.id
        creds = await get_creds(user_id)
        if not creds or not creds[3]:
            keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='back_to_main')]]
            await query.edit_message_text("❌ <b>No account logged in.</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
            return LOGIN_API_ID
        
        text = f"👤 <b>Account Info</b>\n\nPhone: <code>{creds[2]}</code>\nStatus: ✅ <b>Logged In</b>"
        keyboard = [[InlineKeyboardButton("Logout", callback_data='account_logout')], [InlineKeyboardButton("🔙 Back", callback_data='back_to_main')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return MENU

    elif query.data == 'account_logout':
        user_id = update.effective_user.id
        cursor.execute("DELETE FROM credentials WHERE user_id=?", (user_id,))
        conn.commit()
        await query.edit_message_text("✅ <b>Logged out.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='back_to_main')]]), parse_mode='HTML')
        return MENU

    elif query.data == 'back_to_main':
        return await start(update, context)

async def project_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        project_id = int(update.message.text.split('_')[1])
        cursor.execute("SELECT * FROM projects WHERE id=?", (project_id,))
        proj = cursor.fetchone()
        if not proj:
            await update.message.reply_text("Project not found.")
            return

        cursor.execute("SELECT * FROM project_details WHERE project_id=?", (project_id,))
        details = cursor.fetchall()
        
        text = f"📊 <b>Details: {proj[1]}</b>\n"
        text += f"Type: {proj[2].capitalize()} | Total: {proj[3]}\n\n"
        
        if not details:
            text += "No channels created yet."
        else:
            for d in details:
                text += f"🔹 <b>{d[2]}</b>\n"
                text += f"   └ ID: <code>{d[3]}</code>\n"
                text += f"   └ Link: {d[4]}\n\n"
        
        await update.message.reply_text(text, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Error in project_details: {e}")

# --- LOGIN FLOW ---
async def login_api_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['login_api_id'] = update.message.text
    await update.message.reply_text("Send <b>API Hash</b>:", parse_mode='HTML')
    return LOGIN_API_HASH

async def login_api_hash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['login_api_hash'] = update.message.text
    await update.message.reply_text("Send <b>Phone Number</b> (+...):", parse_mode='HTML')
    return LOGIN_PHONE

async def login_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text
    context.user_data['login_phone'] = phone
    client = TelegramClient(StringSession(), context.user_data['login_api_id'], context.user_data['login_api_hash'])
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
        context.user_data['phone_code_hash'] = sent.phone_code_hash
        context.user_data['login_client'] = client 
        await update.message.reply_text("OTP sent! Send <b>OTP</b>:", parse_mode='HTML')
        return LOGIN_OTP
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        await client.disconnect()
        return ConversationHandler.END

async def login_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.user_data['login_client'].sign_in(context.user_data['login_phone'], update.message.text, phone_code_hash=context.user_data['phone_code_hash'])
        session_str = context.user_data['login_client'].session.save()
        user_id = update.effective_user.id
        cursor.execute("INSERT OR REPLACE INTO credentials (user_id, api_id, api_hash, phone, session_str) VALUES (?, ?, ?, ?, ?)",
                      (user_id, context.user_data['login_api_id'], context.user_data['login_api_hash'], context.user_data['login_phone'], session_str))
        conn.commit()
        await update.message.reply_text("✅ <b>Login success!</b>", parse_mode='HTML')
        await context.user_data['login_client'].disconnect()
        return MENU
    except Exception as e:
        if "password" in str(e).lower():
            await update.message.reply_text("Enter <b>2FA Password</b>:", parse_mode='HTML')
            return LOGIN_PASSWORD
        await update.message.reply_text(f"Error: {e}")
        return ConversationHandler.END

async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.user_data['login_client'].sign_in(password=update.message.text)
        session_str = context.user_data['login_client'].session.save()
        user_id = update.effective_user.id
        cursor.execute("INSERT OR REPLACE INTO credentials (user_id, api_id, api_hash, phone, session_str) VALUES (?, ?, ?, ?, ?)",
                      (user_id, context.user_data['login_api_id'], context.user_data['login_api_hash'], context.user_data['login_phone'], session_str))
        conn.commit()
        await update.message.reply_text("✅ <b>Login success!</b>", parse_mode='HTML')
        await context.user_data['login_client'].disconnect()
        return MENU
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        return ConversationHandler.END

# --- PROJECT FLOW ---
async def type_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['project_type'] = 'channel' if 'channel' in query.data else 'group'
    await query.edit_message_text(f"How many {context.user_data['project_type']}s?")
    return WAIT_QUANTITY

async def get_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['quantity'] = int(update.message.text)
    await update.message.reply_text("Enter creation delay (seconds) between channels:")
    return WAIT_DELAY

async def get_delay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['delay'] = int(update.message.text)
    await update.message.reply_text("Enter Folder name or skip:")
    return WAIT_FOLDER

async def get_folder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    folder_name = update.message.text if not update.callback_query else "None"
    user_id = update.effective_user.id
    cursor.execute("INSERT INTO projects (user_id, name, type, quantity, folder, status) VALUES (?, ?, ?, ?, ?, ?)",
                  (user_id, folder_name if folder_name != "None" else "Project", context.user_data['project_type'], 
                   context.user_data['quantity'], folder_name, 'processing'))
    conn.commit()
    asyncio.create_task(execute_creation(update, context, cursor.lastrowid, folder_name, context.user_data['delay'], user_id))
    return ConversationHandler.END

async def execute_creation(update, context, project_id, folder_name, delay, user_id):
    creds = await get_creds(user_id)
    if not creds: return
    client = TelegramClient(StringSession(creds[3]), creds[0], creds[1])
    try:
        await client.connect()
        cursor.execute("SELECT * FROM projects WHERE id=?", (project_id,))
        proj = cursor.fetchone()
        base_name = folder_name if folder_name != "None" else "Channel"
        
        # Fixed naming with hyphen
        naming_base = f"{base_name}-A"
        
        existing_nums = set()
        async for dialog in client.iter_dialogs():
            if dialog.name and dialog.name.startswith(naming_base):
                match = re.search(rf"{naming_base}(\d+)", dialog.name)
                if match: existing_nums.add(int(match.group(1)))
        
        created = 0
        num = 1
        while created < proj[4]:
            if await check_daily_limit(user_id) >= DAILY_LIMIT:
                # Limit reached, wait for next day
                logger.info(f"User {user_id} reached daily limit. Waiting for tomorrow.")
                await update.effective_message.reply_text(f"⚠️ Daily limit (50) reached for project <b>{base_name}</b>. Remaining will be created tomorrow.", parse_mode='HTML')
                
                # Sleep until next day (check every hour)
                while await check_daily_limit(user_id) >= DAILY_LIMIT:
                    await asyncio.sleep(3600)
                continue

            if num in existing_nums: num += 1; continue
            
            try:
                title = f"{naming_base}{num:03d}"
                res = await client(CreateChannelRequest(title=title, about="Svc", megagroup=(proj[3]=='group')))
                channel = res.chats[0]
                await asyncio.sleep(2)
                
                inv = await client(ExportChatInviteRequest(peer=channel))
                cursor.execute("INSERT INTO project_details (project_id, channel_name, channel_id, invite_link) VALUES (?, ?, ?, ?)",
                              (project_id, title, channel.id, inv.link))
                conn.commit()
                
                now = datetime.now()
                cert = (f"<b>CHANNEL BIRTH CERTIFICATE</b>\n\nDate: {now.strftime('%Y-%m-%d')}\n"
                        f"Time: {now.strftime('%I:%M %p')}\nID: <code>{channel.id}</code>\nLink: {inv.link}")
                msg = await client.send_message(channel, cert, parse_mode='html')
                await client(UpdatePinnedMessageRequest(channel=channel, id=msg.id, pm_oneside=True))
                await client(EditPeerFoldersRequest(folder_peers=[InputFolderPeer(peer=channel, folder_id=1)]))
                
                created += 1
                await update_daily_count(user_id, 1)
                num += 1
                
                # Random delay 1-3 minutes (60-180 seconds)
                import random
                wait_time = random.randint(60, 180)
                await asyncio.sleep(wait_time)
            except FloodWaitError as e:
                # Add 10-15 minutes extra random delay as requested
                extra_wait = random.randint(600, 900)
                total_wait = e.seconds + extra_wait
                
                logger.warning(f"FloodWait detected for user {user_id}. Waiting {total_wait}s (includes extra {extra_wait}s).")
                try:
                    await update.effective_message.reply_text(f"⚠️ Telegram limit reached. Bot will sleep for {total_wait//60} minutes to keep your account safe.")
                except: pass
                await asyncio.sleep(total_wait)
            except Exception as e:
                logger.error(f"Loop error: {e}")
                num += 1
                await asyncio.sleep(10)
        cursor.execute("UPDATE projects SET status='complete' WHERE id=?", (project_id,))
        conn.commit()
    finally: await client.disconnect()

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_error_handler(error_handler)
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MENU: [CallbackQueryHandler(menu_handler)],
            WAIT_TYPE: [CallbackQueryHandler(type_handler)],
            WAIT_QUANTITY: [MessageHandler(filters.TEXT, get_quantity)],
            WAIT_DELAY: [MessageHandler(filters.TEXT, get_delay)],
            WAIT_FOLDER: [MessageHandler(filters.TEXT, get_folder), CallbackQueryHandler(get_folder, pattern='^skip_folder$')],
            LOGIN_API_ID: [MessageHandler(filters.TEXT, login_api_id)],
            LOGIN_API_HASH: [MessageHandler(filters.TEXT, login_api_hash)],
            LOGIN_PHONE: [MessageHandler(filters.TEXT, login_phone)],
            LOGIN_OTP: [MessageHandler(filters.TEXT, login_otp)],
            LOGIN_PASSWORD: [MessageHandler(filters.TEXT, login_password)],
        },
        fallbacks=[CommandHandler("start", start)]
    ))
    app.add_handler(MessageHandler(filters.Regex(r'^/details_\d+$'), project_details))
    app.run_polling()

if __name__ == '__main__': main()