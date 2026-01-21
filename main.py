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

# Database setup
try:
    conn = sqlite3.connect('projects.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS projects 
                     (id INTEGER PRIMARY KEY, name TEXT, type TEXT, quantity INTEGER, 
                      folder TEXT, folder_id INTEGER, status TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS daily_stats (date TEXT PRIMARY KEY, count INTEGER DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS credentials 
                     (id INTEGER PRIMARY KEY, api_id TEXT, api_hash TEXT, phone TEXT, session_str TEXT)''')
    conn.commit()
except sqlite3.Error as e:
    logger.error(f"Database error during setup: {e}")
    sys.exit(1)

# States
(MENU, WAIT_TYPE, WAIT_QUANTITY, WAIT_FOLDER, 
 LOGIN_API_ID, LOGIN_API_HASH, LOGIN_PHONE, LOGIN_OTP, LOGIN_PASSWORD) = range(9)

async def check_daily_limit():
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute("SELECT count FROM daily_stats WHERE date=?", (today,))
        row = cursor.fetchone()
        if not row:
            cursor.execute("INSERT INTO daily_stats (date, count) VALUES (?, 0)", (today,))
            conn.commit()
            return 0
        return row[0]
    except sqlite3.Error as e:
        logger.error(f"Error checking daily limit: {e}")
        return 0

async def update_daily_count(add):
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute("UPDATE daily_stats SET count = count + ? WHERE date=?", (add, today))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Error updating daily count: {e}")

async def get_creds():
    try:
        cursor.execute("SELECT api_id, api_hash, phone, session_str FROM credentials LIMIT 1")
        return cursor.fetchone()
    except sqlite3.Error as e:
        logger.error(f"Error getting credentials: {e}")
        return None

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    
    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    message = (
        f"An exception was raised while handling an update\n"
        f"<code>update = {update_str}</code>\n\n"
        f"<code>context.user_data = {str(context.user_data)}</code>\n\n"
        f"<code>{tb_string}</code>"
    )
    
    # If possible, notify the user
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ An unexpected error occurred. Please try again later or contact the developer.",
            parse_mode='HTML'
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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
    except Exception as e:
        logger.error(f"Error in start command: {e}")

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        
        if query.data == 'menu_add':
            creds = await get_creds()
            if not creds or not creds[3]:
                keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back_to_main')]]
                await query.edit_message_text("❌ <b>Login Required!</b>\n\nProject add karne ke liye pehle <b>My Account</b> mein jaakar login kare.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                return MENU
                
            keyboard = [
                [InlineKeyboardButton("📢 Create Channel", callback_data='type_channel'),
                 InlineKeyboardButton("👥 Create Group", callback_data='type_group')],
                [InlineKeyboardButton("🔙 Back", callback_data='back_to_main')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text('Select what to create:', reply_markup=reply_markup)
            return WAIT_TYPE

        elif query.data == 'menu_status':
            cursor.execute("SELECT * FROM projects ORDER BY created_at DESC LIMIT 10")
            projects = cursor.fetchall()
            text = "📋 <b>Recent Projects Status</b>\n\n"
            if not projects:
                text += "No projects yet!"
            else:
                for proj in projects:
                    status_icon = "✅" if proj[6] == 'complete' else "⏳"
                    created_at = proj[7] if len(proj) > 7 else None
                    time_str = created_at.split(' ')[1][:5] if created_at and ' ' in created_at else "--:--"
                    text += f"{status_icon} <b>{proj[1]}</b> ({proj[2]})\n"
                    text += f"   └ Qty: {proj[3]} | Folder: {proj[4]} | {time_str}\n\n"
            
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back_to_main')]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
            return MENU

        elif query.data == 'menu_account':
            creds = await get_creds()
            if not creds or not creds[3]:
                keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='back_to_main')]]
                await query.edit_message_text("❌ <b>No account logged in.</b>\n\nPlease provide <b>API ID</b> to start login:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                return LOGIN_API_ID
            
            text = f"👤 <b>Account Info</b>\n\nPhone: <code>{creds[2]}</code>\nAPI ID: <code>{creds[0]}</code>\nStatus: ✅ <b>Logged In</b>"
            keyboard = [
                [InlineKeyboardButton("Logout", callback_data='account_logout')],
                [InlineKeyboardButton("🔙 Back", callback_data='back_to_main')]
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
            return MENU

        elif query.data == 'account_logout':
            cursor.execute("DELETE FROM credentials")
            conn.commit()
            await query.edit_message_text("✅ <b>Logged out successfully.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='back_to_main')]]), parse_mode='HTML')
            return MENU

        elif query.data == 'back_to_main':
            return await start(update, context)
    except Exception as e:
        logger.error(f"Error in menu_handler: {e}")

# --- LOGIN FLOW ---
async def login_api_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text
        if text.lower() == '/start': return await start(update, context)
        context.user_data['login_api_id'] = text
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='back_to_main')]]
        await update.message.reply_text("Send <b>API Hash</b>:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return LOGIN_API_HASH
    except Exception as e:
        logger.error(f"Error in login_api_id: {e}")

async def login_api_hash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text
        if text.lower() == '/start': return await start(update, context)
        context.user_data['login_api_hash'] = text
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='back_to_main')]]
        await update.message.reply_text("Send <b>Phone Number</b> (with country code, e.g., +91...):", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return LOGIN_PHONE
    except Exception as e:
        logger.error(f"Error in login_api_hash: {e}")

async def login_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        phone = update.message.text
        if phone.lower() == '/start': return await start(update, context)
        context.user_data['login_phone'] = phone
        
        api_id = context.user_data['login_api_id']
        api_hash = context.user_data['login_api_hash']
        
        client = TelegramClient(StringSession(), api_id, api_hash)
        await client.connect()
        try:
            sent = await client.send_code_request(phone)
            context.user_data['phone_code_hash'] = sent.phone_code_hash
            context.user_data['login_client'] = client 
            keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='back_to_main')]]
            await update.message.reply_text("OTP sent! Please send the <b>OTP</b>:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
            return LOGIN_OTP
        except Exception as e:
            await update.message.reply_text(f"Error: {e}\n\nRestart login with /start", parse_mode='HTML')
            await client.disconnect()
            return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in login_phone: {e}")

async def login_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        otp = update.message.text
        if otp.lower() == '/start': return await start(update, context)
        client = context.user_data['login_client']
        phone = context.user_data['login_phone']
        code_hash = context.user_data['phone_code_hash']
        
        try:
            await client.sign_in(phone, otp, phone_code_hash=code_hash)
            session_str = client.session.save()
            cursor.execute("DELETE FROM credentials")
            cursor.execute("INSERT INTO credentials (api_id, api_hash, phone, session_str) VALUES (?, ?, ?, ?)",
                          (context.user_data['login_api_id'], context.user_data['login_api_hash'], phone, session_str))
            conn.commit()
            await update.message.reply_text("✅ <b>Login successful!</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Go to Menu", callback_data='back_to_main')]]), parse_mode='HTML')
            await client.disconnect()
            return MENU
        except Exception as e:
            if "password" in str(e).lower():
                keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='back_to_main')]]
                await update.message.reply_text("This account has 2FA. Please send your <b>Password</b>:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
                return LOGIN_PASSWORD
            await update.message.reply_text(f"Error: {e}")
            await client.disconnect()
            return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in login_otp: {e}")

async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        password = update.message.text
        if password.lower() == '/start': return await start(update, context)
        client = context.user_data['login_client']
        try:
            await client.sign_in(password=password)
            session_str = client.session.save()
            cursor.execute("DELETE FROM credentials")
            cursor.execute("INSERT INTO credentials (api_id, api_hash, phone, session_str) VALUES (?, ?, ?, ?)",
                          (context.user_data['login_api_id'], context.user_data['login_api_hash'], context.user_data['login_phone'], session_str))
            conn.commit()
            await update.message.reply_text("✅ <b>Login successful (2FA)!</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Go to Menu", callback_data='back_to_main')]]), parse_mode='HTML')
            await client.disconnect()
            return MENU
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")
            await client.disconnect()
            return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in login_password: {e}")

# --- PROJECT FLOW ---
async def type_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        
        if query.data == 'back_to_main':
            return await start(update, context)
            
        context.user_data['project_type'] = 'channel' if 'channel' in query.data else 'group'
        await query.edit_message_text(f"How many {context.user_data['project_type']}s create karne hai?")
        return WAIT_QUANTITY
    except Exception as e:
        logger.error(f"Error in type_handler: {e}")

async def get_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text)
        context.user_data['quantity'] = qty
        keyboard = [[InlineKeyboardButton("Skip Folder", callback_data='skip_folder')], [InlineKeyboardButton("🔙 Back", callback_data='back_to_main')]]
        await update.message.reply_text('Folder name batao (like Channel-A) ya skip karo:', reply_markup=InlineKeyboardMarkup(keyboard))
        return WAIT_FOLDER
    except ValueError:
        await update.message.reply_text('Valid number daal bhai!')
        return WAIT_QUANTITY
    except Exception as e:
        logger.error(f"Error in get_quantity: {e}")

async def get_folder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        folder_name = "None"
        
        if query:
            await query.answer()
            if query.data == 'back_to_main': return await start(update, context)
            folder_name = "None"
            await query.edit_message_text("Starting creation...")
        else:
            folder_name = update.message.text
            await update.message.reply_text(f"Starting creation in: {folder_name}...")

        cursor.execute("INSERT INTO projects (name, type, quantity, folder, status) VALUES (?, ?, ?, ?, ?)",
                      (folder_name if folder_name != "None" else "Channel", context.user_data['project_type'], 
                       context.user_data['quantity'], folder_name, 'processing'))
        conn.commit()
        project_id = cursor.lastrowid

        asyncio.create_task(execute_creation(update, context, project_id, folder_name))
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in get_folder: {e}")

async def execute_creation(update, context, project_id, folder_name):
    creds = await get_creds()
    if not creds: return
    
    client = TelegramClient(StringSession(creds[3]), creds[0], creds[1])
    try:
        await client.connect()
        cursor.execute("SELECT * FROM projects WHERE id=?", (project_id,))
        proj = cursor.fetchone()
        if not proj: return
        
        total_qty = proj[3]
        p_type = proj[2]
        base_name = folder_name if folder_name != "None" else "Channel"
        
        existing_numbers = set()
        try:
            async for dialog in client.iter_dialogs():
                if dialog.name and dialog.name.startswith(base_name):
                    match = re.search(rf"{re.escape(base_name)}(\d+)", dialog.name)
                    if match: existing_numbers.add(int(match.group(1)))
        except Exception as e:
            logger.error(f"Error iterating dialogs: {e}")
        
        created_count = 0
        num = 1
        while created_count < total_qty:
            if await check_daily_limit() >= 20: 
                logger.info("Daily limit reached during execution.")
                return
            if num in existing_numbers:
                num += 1
                continue
            try:
                title = f"{base_name}{num:03d}"
                result = await client(CreateChannelRequest(
                    title=title, 
                    about="Service", 
                    megagroup=(p_type == 'group')
                ))
                channel = result.chats[0]
                await asyncio.sleep(2)
                
                invite_link = "None"
                try:
                    invite = await client(ExportChatInviteRequest(peer=channel))
                    invite_link = invite.link
                except Exception as e:
                    logger.warning(f"Failed to export invite link: {e}")

                now = datetime.now()
                creation_date = now.strftime("%Y-%m-%d")
                creation_time = now.strftime("%I:%M %p")
                
                cert_msg = (
                    "<b>CHANNEL BIRTH CERTIFICATE</b>\n"
                    "----------------------------------\n\n"
                    "<b>1. Channel Age Details:</b>\n"
                    f"   -Creation Date: {creation_date}\n"
                    f"   -Creation Time: {creation_time}\n"
                    f"   -Channel Type: {p_type.capitalize()}\n\n"
                    "<b>2. Key Identification:</b>\n"
                    f"   -Unique Channel ID: <code>{channel.id}</code>\n"
                    f"   -Initial Invite Link: {invite_link}\n\n"
                    "<b>3. Status &amp; Goal:</b>\n"
                    "   -Initial Users: 1 (Creator)\n\n"
                    "<b>4. User/Data Source (For Future Value):</b>\n"
                    "   -Current Users: None\n"
                    "   -User Source/Acquisition Method: None\n\n"
                    "<i>Note: This post is pinned to confirm the channel's creation age.</i>"
                )

                try:
                    sent_cert = await client.send_message(channel, cert_msg, parse_mode='html')
                    await client(UpdatePinnedMessageRequest(channel=channel, id=sent_cert.id, pm_oneside=True))
                except Exception as e:
                    logger.error(f"Cert error: {e}")

                try:
                    await client(EditPeerFoldersRequest(folder_peers=[InputFolderPeer(peer=channel, folder_id=1)]))
                except Exception as e:
                    logger.error(f"Archive error: {e}")
                
                created_count += 1
                await update_daily_count(1)
                num += 1
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Loop error during channel creation: {e}")
                if "flood" in str(e).lower():
                    logger.warning("Flood wait triggered, stopping execution.")
                    return
                num += 1
                continue
        
        cursor.execute("UPDATE projects SET status='complete' WHERE id=?", (project_id,))
        conn.commit()
    except Exception as e:
        logger.error(f"Fatal error in execute_creation: {e}")
    finally:
        await client.disconnect()

def main():
    try:
        app = Application.builder().token(BOT_TOKEN).build()
        
        # Add global error handler
        app.add_error_handler(error_handler)
        
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start)],
            states={
                MENU: [CallbackQueryHandler(menu_handler)],
                WAIT_TYPE: [CallbackQueryHandler(type_handler)],
                WAIT_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_quantity)],
                WAIT_FOLDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_folder),
                             CallbackQueryHandler(get_folder, pattern='^skip_folder$'),
                             CallbackQueryHandler(type_handler, pattern='^back_to_main$')],
                LOGIN_API_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_api_id),
                              CallbackQueryHandler(menu_handler, pattern='^back_to_main$')],
                LOGIN_API_HASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_api_hash),
                                CallbackQueryHandler(menu_handler, pattern='^back_to_main$')],
                LOGIN_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_phone),
                             CallbackQueryHandler(menu_handler, pattern='^back_to_main$')],
                LOGIN_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_otp),
                           CallbackQueryHandler(menu_handler, pattern='^back_to_main$')],
                LOGIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_password),
                                CallbackQueryHandler(menu_handler, pattern='^back_to_main$')],
            },
            fallbacks=[CommandHandler("start", start), CallbackQueryHandler(menu_handler, pattern='^back_to_main$')]
        )
        
        app.add_handler(conv_handler)
        logger.info("Bot started successfully!")
        app.run_polling()
    except Exception as e:
        logger.critical(f"Critical error in main loop: {e}")

if __name__ == '__main__':
    main()