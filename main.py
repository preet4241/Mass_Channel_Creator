import asyncio
import sqlite3
import logging
from telethon import TelegramClient
from telethon.tl.functions.channels import CreateChannelRequest
from telethon.tl.functions.messages import UpdatePinnedMessageRequest
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
                  folder TEXT, status TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
conn.commit()

client = TelegramClient('session', API_ID, API_HASH)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Add Projects", callback_data='add_projects')],
        [InlineKeyboardButton("📊 Status", callback_data='status')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('🤖 **Channel Manager Bot**\n\nChoose option:', reply_markup=reply_markup, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'add_projects':
        keyboard = [[InlineKeyboardButton("📢 Create Channel", callback_data='create_channel'),
                     InlineKeyboardButton("👥 Create Group", callback_data='create_group')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text('Select type:', reply_markup=reply_markup)
    
    elif query.data == 'create_channel':
        context.user_data['project_type'] = 'channel'
        await query.edit_message_text('How many channels create karne hai?')
        return 'WAIT_QUANTITY'
    
    elif query.data == 'create_group':
        context.user_data['project_type'] = 'group'
        await query.edit_message_text('How many groups create karne hai?')
        return 'WAIT_QUANTITY'
    
    elif query.data == 'status':
        cursor.execute("SELECT * FROM projects ORDER BY created_at DESC")
        projects = cursor.fetchall()
        if not projects:
            await query.edit_message_text('No projects yet!')
            return
        
        text = "📋 **Projects Status**\n\n"
        for proj in projects[:10]:  # Show last 10
            status = "✅ Complete" if proj[5] == 'complete' else "⏳ Processing"
            text += f"• {proj[1]} ({proj[2]}) - {proj[3]} - {status}\n"
        await query.edit_message_text(text, parse_mode='Markdown')

async def get_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text)
        context.user_data['quantity'] = qty
        await update.message.reply_text('Folder name batao (like Channel-A):')
        return 'WAIT_FOLDER'
    except:
        await update.message.reply_text('Number daal bhai!')

async def get_folder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project_name = f"{context.user_data['project_type'].title()}-{context.user_data['quantity']:03d}"
    cursor.execute("INSERT INTO projects (name, type, quantity, folder, status) VALUES (?, ?, ?, ?, ?)",
                  (project_name, context.user_data['project_type'], context.user_data['quantity'], 
                   update.message.text, 'pending'))
    conn.commit()
    
    await update.message.reply_text(f'✅ **Project Added!**\n\n'
                                   f'Name: `{project_name}`\n'
                                   f'Folder: {update.message.text}\n\n'
                                   f'Run script: `/run {project_name}`', parse_mode='Markdown')
    return ConversationHandler.END

async def run_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await client.is_user_authorized():
        await client.start(phone=PHONE)
    
    project_name = context.args[0] if context.args else None
    if not project_name:
        await update.message.reply_text('Project name de: `/run ProjectName`')
        return
    
    cursor.execute("SELECT * FROM projects WHERE name=? AND status='pending'", (project_name,))
    proj = cursor.fetchone()
    if not proj:
        await update.message.reply_text('Project nahi mila!')
        return
    
    await update.message.reply_text(f'🚀 Starting {proj[3]} {proj[2].upper()}s in {proj[4]} folder...')
    
    created_channels = []
    for i in range(proj[3]):
        try:
            title = f"{proj[4]}{i+1:03d}"
            result = await client(CreateChannelRequest(
                title=title, 
                about="Birth Certificate Services | DM for details",
                megagroup=False  # Channel
            ))
            channel = result.chats[0]
            created_channels.append(channel)
            
            # Birth certificate post
            # Note: birth_cert.jpg needs to exist
            try:
                await client.send_file(channel, 'birth_cert.jpg', 
                                     caption="🔥 **Birth Certificate Available**\n\n"
                                            "✅ Instant delivery\n"
                                            "💰 Best rates\n"
                                            "📱 DM @yourusername\n\n"
                                            f"Channel-A{i+1:03d}")
            except Exception as e:
                await update.message.reply_text(f'Error sending file: {str(e)}')
            
            # Pin message
            await client(UpdatePinnedMessageRequest(channel=channel, id=1, pm_oneside=True))
            
            # Archive
            from telethon.tl.functions.messages import UpdateDialogUnreadMarkRequest
            await client(UpdateDialogUnreadMarkRequest(peer=channel, unread=False))
            
            await asyncio.sleep(120)  # Rate limit
            
        except Exception as e:
            await update.message.reply_text(f'Error {i+1}: {str(e)}')
            continue
    
    # Update status
    cursor.execute("UPDATE projects SET status='complete' WHERE id=?", (proj[0],))
    conn.commit()
    
    await update.message.reply_text(f'✅ **Complete!** {len(created_channels)}/{proj[3]} channels ready in {proj[4]} folder!')

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern='^(create_channel|create_group)$')],
        states={
            'WAIT_QUANTITY': [MessageHandler(filters.TEXT & ~filters.COMMAND, get_quantity)],
            'WAIT_FOLDER': [MessageHandler(filters.TEXT & ~filters.COMMAND, get_folder)]
        },
        fallbacks=[]
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("run", run_project))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("Bot started!")
    app.run_polling()

if __name__ == '__main__':
    main()