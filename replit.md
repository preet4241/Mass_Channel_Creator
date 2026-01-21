# Telegram Channel Creator Bot

## Overview

This is a Telegram bot application that automates the creation and management of Telegram channels. The bot allows users to create channels through a conversational interface, tracks daily creation limits, and organizes projects with folder management capabilities.

The application uses two Telegram libraries working together:
- **Telethon** - User client for performing privileged actions like creating channels
- **python-telegram-bot** - Bot interface for user interactions via commands and inline keyboards

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Core Components

**Dual-Client Architecture**
- The system uses two separate Telegram connections: a user client (Telethon) for administrative actions that require user-level permissions (channel creation, folder management), and a bot client (python-telegram-bot) for handling user interactions through the bot interface.
- This separation is necessary because Telegram bots cannot create channels on behalf of users - only user accounts can perform this action.

**Conversation Flow**
- Uses python-telegram-bot's ConversationHandler pattern with defined states (WAIT_TYPE, WAIT_QUANTITY, WAIT_FOLDER) to guide users through multi-step channel creation process.
- Inline keyboards provide the user interface for selecting options.

**Data Storage**
- SQLite database (`projects.db`) stores project metadata and daily statistics.
- Two tables: `projects` for tracking created channels with their metadata, and `daily_stats` for rate limiting.

**Rate Limiting**
- Daily creation limits are tracked to prevent abuse and comply with Telegram's rate limits.
- Statistics are stored per-date and checked before allowing new channel creation.

### Authentication

- Telethon user client authenticates with API credentials (API_ID, API_HASH) and phone number
- Bot client authenticates with BOT_TOKEN
- Session persistence via Telethon's session file

## External Dependencies

### Telegram Services
- **Telegram Bot API** - Primary user interface through bot commands and callbacks
- **Telegram User API (MTProto)** - Channel creation and management operations via Telethon

### Database
- **SQLite** - Local file-based database for project tracking and rate limiting

### Python Packages
- `python-telegram-bot` (v20.7) - Bot interface and conversation handling
- `telethon` (v1.36.0) - MTProto client for user-level Telegram operations

### Credentials Required
- Telegram API ID and Hash (from my.telegram.org)
- Phone number for user account authentication
- Bot token (from @BotFather)

**Security Note**: The current implementation has hardcoded credentials in main.py. These should be moved to environment variables for production use.