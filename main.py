import asyncio
import sqlite3
import logging
import re
from datetime import datetime
from telethon import TelegramClient
from telethon.tl.functions.channels import CreateChannelRequest
from telethon.tl.functions.messages import UpdatePinnedMessageRequest
from telethon.tl.functions.folders import EditPeerFoldersRequest
from telethon.tl.types import InputFolderPeer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Config
API_ID = '22880380'
API_HASH = '08dae0d98b2dc8f8dc4e6a9ff97a071b'
PHONE = '+917000275199'
BOT_TOKEN = '8028312869:AAErsD7WmHHw11c2lL2Jdoj_DBU4bqRv_kQ'

# Database setup
conn = sqlite3.connect('projects.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS projects 
                 (id INTEGER PRIMARY KEY, name TEXT, type TEXT, quantity INTEGER, 
                  folder TEXT, folder_id INTEGER, status TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS daily_stats (date TEXT PRIMARY KEY, count INTEGER DEFAULT 0)''')
conn.commit()

# States
WAIT_TYPE, WAIT_QUANTITY, WAIT_FOLDER = range(3)

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
                [InlineKeyboardButton("📊 Status", callback_data='status')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('🤖 **Smart Manager Bot**\n\nChoose what to create:', reply_markup=reply_markup, parse_mode='Markdown')
    return WAIT_TYPE

async def type_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'status':
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

    context.user_data['project_type'] = 'channel' if 'channel' in query.data else 'group'
    await query.edit_message_text(f"How many {context.user_data['project_type']}s create karne hai? (Total Project Quantity)")
    return WAIT_QUANTITY

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

    asyncio.create_task(execute_creation(update, context, project_id, folder_name))
    return ConversationHandler.END

async def execute_creation(update, context, project_id, folder_name):
    client = TelegramClient('session', API_ID, API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            await client.start(phone=PHONE)

        cursor.execute("SELECT * FROM projects WHERE id=?", (project_id,))
        proj = cursor.fetchone()
        total_qty = proj[3]
        p_type = proj[2]
        
        base_name = folder_name if folder_name != "None" else "Channel"
        
        existing_numbers = set()
        async for dialog in client.iter_dialogs():
            if dialog.name and dialog.name.startswith(base_name):
                match = re.search(rf"{re.escape(base_name)}(\d+)", dialog.name)
                if match:
                    existing_numbers.add(int(match.group(1)))
        
        created_count = 0
        num = 1
        while created_count < total_qty:
            if await check_daily_limit() >= 20:
                msg = f"⏳ Daily limit (20) reached. Project {proj[1]} paused."
                if update.message: await update.message.reply_text(msg)
                else: await update.callback_query.message.reply_text(msg)
                return

            if num in existing_numbers:
                num += 1
                continue

            try:
                title = f"{base_name}{num:03d}"
                result = await client(CreateChannelRequest(
                    title=title, 
                    about="Birth Certificate Services",
                    megagroup=(p_type == 'group')
                ))
                channel = result.chats[0]
                
                await asyncio.sleep(2)
                try:
                    await client.send_file(channel, 'birth_cert.jpg', caption=f"🔥 **Service Available**\n\n{title}")
                    await client(UpdatePinnedMessageRequest(channel=channel, id=1, pm_oneside=True))
                except: pass

                try:
                    await client(EditPeerFoldersRequest(folder_peers=[InputFolderPeer(peer=channel, folder_id=1)]))
                except: pass
                
                created_count += 1
                await update_daily_count(1)
                num += 1
                await asyncio.sleep(60)
                
            except Exception as e:
                msg = f"Error creating {title}: {str(e)}"
                if "flood" in str(e).lower():
                    await update.message.reply_text("🛑 Flood wait triggered. Stopping for now.")
                    return
                if update.message: await update.message.reply_text(msg)
                num += 1
                continue

        cursor.execute("UPDATE projects SET status='complete' WHERE id=?", (project_id,))
        conn.commit()
        
        final_msg = f"✅ **Project Complete!** Created {created_count} {p_type}s."
        if update.message: await update.message.reply_text(final_msg)
        else: await update.callback_query.message.reply_text(final_msg)
    finally:
        await client.disconnect()

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAIT_TYPE: [CallbackQueryHandler(type_handler)],
            WAIT_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_quantity)],
            WAIT_FOLDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_folder),
                         CallbackQueryHandler(get_folder, pattern='^skip_folder$')]
        },
        fallbacks=[CommandHandler("start", start)]
    )
    
    app.add_handler(conv_handler)
    print("Bot started!")
    app.run_polling()

if __name__ == '__main__':
    main()