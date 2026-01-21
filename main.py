import asyncio
import sqlite3
import logging
import re
import os
from datetime import datetime
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import CreateChannelRequest
from telethon.tl.functions.messages import UpdatePinnedMessageRequest, ExportChatInviteRequest
from telethon.tl.functions.folders import EditPeerFoldersRequest
from telethon.tl.types import InputFolderPeer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Config
BOT_TOKEN = '8028312869:AAErsD7WmHHw11c2lL2Jdoj_DBU4bqRv_kQ'

# Database setup
conn = sqlite3.connect('projects.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS projects 
                 (id INTEGER PRIMARY KEY, name TEXT, type TEXT, quantity INTEGER, 
                  folder TEXT, folder_id INTEGER, status TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS daily_stats (date TEXT PRIMARY KEY, count INTEGER DEFAULT 0)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS credentials 
                 (id INTEGER PRIMARY KEY, api_id TEXT, api_hash TEXT, phone TEXT, session_str TEXT)''')
conn.commit()

# States
(MENU, WAIT_TYPE, WAIT_QUANTITY, WAIT_FOLDER, 
 LOGIN_API_ID, LOGIN_API_HASH, LOGIN_PHONE, LOGIN_OTP, LOGIN_PASSWORD) = range(9)

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

async def get_creds():
    cursor.execute("SELECT api_id, api_hash, phone, session_str FROM credentials LIMIT 1")
    return cursor.fetchone()

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

# --- LOGIN FLOW ---
async def login_api_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text.lower() == '/start': return await start(update, context)
    context.user_data['login_api_id'] = text
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='back_to_main')]]
    await update.message.reply_text("Send <b>API Hash</b>:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    return LOGIN_API_HASH

async def login_api_hash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text.lower() == '/start': return await start(update, context)
    context.user_data['login_api_hash'] = text
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='back_to_main')]]
    await update.message.reply_text("Send <b>Phone Number</b> (with country code, e.g., +91...):", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    return LOGIN_PHONE

async def login_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def login_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# --- PROJECT FLOW ---
async def type_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'back_to_main':
        return await start(update, context)
        
    context.user_data['project_type'] = 'channel' if 'channel' in query.data else 'group'
    await query.edit_message_text(f"How many {context.user_data['project_type']}s create karne hai?")
    return WAIT_QUANTITY

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

async def get_folder(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def execute_creation(update, context, project_id, folder_name):
    creds = await get_creds()
    if not creds: return
    
    client = TelegramClient(StringSession(creds[3]), creds[0], creds[1])
    try:
        await client.connect()
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
            if await check_daily_limit() >= 20: return
            if num in existing_numbers:
                num += 1
                continue
            try:
                title = f"{base_name}{num:03d}"
                # Create private channel (megagroup False and no username)
                result = await client(CreateChannelRequest(
                    title=title, 
                    about="Service", 
                    megagroup=(p_type == 'group')
                ))
                channel = result.chats[0]
                
                # Wait for channel to be ready
                await asyncio.sleep(2)
                
                # Get Invite Link
                invite_link = "None"
                try:
                    invite = await client(ExportChatInviteRequest(peer=channel))
                    invite_link = invite.link
                except: pass

                # Get Creation Stats
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

                # Post & Pin Certificate
                try:
                    sent_cert = await client.send_message(channel, cert_msg, parse_mode='html')
                    await client(UpdatePinnedMessageRequest(channel=channel, id=sent_cert.id, pm_oneside=True))
                except Exception as e:
                    print(f"Cert error: {e}")

                # Archive
                try:
                    await client(EditPeerFoldersRequest(folder_peers=[InputFolderPeer(peer=channel, folder_id=1)]))
                except: pass
                
                created_count += 1
                await update_daily_count(1)
                num += 1
                await asyncio.sleep(60)
            except Exception as e:
                print(f"Loop error: {e}")
                num += 1
                continue
        cursor.execute("UPDATE projects SET status='complete' WHERE id=?", (project_id,))
        conn.commit()
    finally:
        await client.disconnect()

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
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
    print("Bot started!")
    app.run_polling()

if __name__ == '__main__':
    main()