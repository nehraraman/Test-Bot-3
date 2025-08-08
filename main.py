import os
import psycopg2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode
import logging
import datetime

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration (Using hardcoded token for now; move to env var in production)
BOT_TOKEN = "8335379785:AAHK01gK2gaAsF75DoAD0tf-vNPKyJeUq_I"
# 
# Database configuration: PostgreSQL if DATABASE_URL is set, otherwise SQLite
import sqlite3

# ====== FIXED CONSTANTS ======
CHANNEL_LINK = "https://t.me/X_Reward_botChannel"
SUPPORT_GROUP = "https://t.me/xrewardchannel"
ADMIN_IDS = [1756808131]  # Apna Telegram numeric ID
BOT_USERNAME = "@X_Reward_Bot"  # Bot ka username
ADMIN_USERNAME = "@XRewardAdmin"  # Apna admin username

# Conversation states for adding/editing tasks
TASK_TITLE, TASK_DESCRIPTION, TASK_LINK, TASK_REWARD = range(4)

# Conversation states for updating links
CHANNEL_LINK_STATE, SUPPORT_GROUP_STATE = range(4, 6)
# =============================


DATABASE_URL = os.getenv("DATABASE_URL")
USE_SQLITE = not bool(DATABASE_URL)

# Helper to adapt SQL placeholders for SQLite / PostgreSQL
def ph(query: str) -> str:
    return query.replace("%s", "?") if USE_SQLITE else query


if USE_SQLITE:
    logger.warning("DATABASE_URL not set. Using SQLite local database 'database.db'.")
else:
    logger.info("Using PostgreSQL database from DATABASE_URL.")

# Helper: get database connection
def get_db():
    if USE_SQLITE:
        return sqlite3.connect("database.db")
    else:
        import psycopg2
        return psycopg2.connect(DATABASE_URL)

# Initialize Database
def init_db():
    conn = get_db()
    try:
        c = conn.cursor()
        # Create tables
        c.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            coins INTEGER DEFAULT 0,
            referrer_id INTEGER,
            joined_at TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS tasks (
            task_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            link TEXT,
            reward INTEGER
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS task_submissions (
            submission_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            task_id INTEGER,
            proof_url TEXT,
            status TEXT DEFAULT 'pending',
            submitted_at TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS daily_claims (
            user_id INTEGER PRIMARY KEY,
            last_claim TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS referrals (
            referrer_id INTEGER,
            referred_id INTEGER,
            PRIMARY KEY (referrer_id, referred_id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )""")
        # Insert default settings if not exists
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                  ('CHANNEL_LINK', 'https://t.me/X_Reward_botChannel'))
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                  ('SUPPORT_GROUP', 'https://t.me/your_support_group'))
        conn.commit()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise
    finally:
        conn.close()

# Helper function to get setting
def get_setting(key):
    conn = get_db()
    try:
        c = conn.cursor()
        placeholder = "?" if USE_SQLITE else "%s"
        c.execute(f'SELECT value FROM settings WHERE key = {placeholder}', (key,))
        result = c.fetchone()
        return result[0] if result else None
    finally:
        conn.close()

# Helper function to update setting
def update_setting(key, value):
    conn = get_db()
    try:
        c = conn.cursor()
        if USE_SQLITE:
            c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        else:
            c.execute(ph('INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = %s'),
                      (key, value, value))
        conn.commit()
    finally:
        conn.close()


# Helper function to check channel membership
async def check_channel_membership(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    try:
        channel_link = get_setting('CHANNEL_LINK')
        channel_username = channel_link.split('/')[-1]
        if not channel_username.startswith('@'):
            channel_username = '@' + channel_username  # Ensure it starts with @
        member = await context.bot.get_chat_member(chat_id=channel_username, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking channel membership: {e}")
        return False

# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    referrer_id = int(args[0]) if args and args[0].isdigit() else None
    logger.info(f"Received /start from user {user.id} with referrer {referrer_id}")

    if await check_channel_membership(context, user.id):
        conn = get_db()
        try:
            c = conn.cursor()
            c.execute(ph('SELECT * FROM users WHERE user_id = %s'), (user.id,))
            if not c.fetchone():
                c.execute(ph('INSERT INTO users (user_id, username, coins, referrer_id, joined_at) VALUES (%s, %s, %s, %s, %s)'),
                          (user.id, user.username or 'Unknown', 100, referrer_id, datetime.datetime.now()))
                if referrer_id:
                    c.execute(ph('SELECT * FROM users WHERE user_id = %s'), (referrer_id,))
                    if c.fetchone():
                        c.execute(ph('INSERT INTO referrals (referrer_id, referred_id) VALUES (%s, %s) ON CONFLICT DO NOTHING'),
                                  (referrer_id, user.id))
                        c.execute(ph('UPDATE users SET coins = coins + 200 WHERE user_id = %s'), (referrer_id,))
                conn.commit()
            keyboard = [
                [InlineKeyboardButton("📋 Tasks", callback_data='tasks'), InlineKeyboardButton("💰 Coins", callback_data='coins')],
                [InlineKeyboardButton("🎁 Daily Reward", callback_data='daily'), InlineKeyboardButton("🤝 Refer", callback_data='refer')],
                [InlineKeyboardButton("🏆 Leaderboard", callback_data='leaderboard'), InlineKeyboardButton("👥 Top Inviters", callback_data='top_inviters')],
                [InlineKeyboardButton("📞 Support", callback_data='support'), InlineKeyboardButton("🔙 Back", callback_data='back')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"Welcome, {user.first_name}! 🎉\nYou have 100 coins for joining!\nUse the buttons below to explore the bot.",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error in start command: {e}")
            await update.message.reply_text("An error occurred. Please try again.")
        finally:
            conn.close()
    else:
        channel_link = get_setting('CHANNEL_LINK')
        keyboard = [[InlineKeyboardButton("Join Channel", url=channel_link)],
                    [InlineKeyboardButton("✅ Check Join", callback_data='check_join')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"Please join our channel to use the bot: {channel_link}\nAfter joining, click 'Check Join'.",
            reply_markup=reply_markup
        )

# /refer command
async def refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await check_channel_membership(context, user.id):
        channel_link = get_setting('CHANNEL_LINK')
        keyboard = [[InlineKeyboardButton("Join Channel", url=channel_link)],
                    [InlineKeyboardButton("✅ Check Join", callback_data='check_join')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"You must join our channel to use this command: {channel_link}\nAfter joining, click 'Check Join'.",
            reply_markup=reply_markup
        )
        return
    
    user_id = user.id
    bot_username = context.bot.username
    referral_link = f"https://t.me/{bot_username}?start={user_id}"
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(ph('SELECT COUNT(*) FROM referrals WHERE referrer_id = %s'), (user_id,))
        referral_count = c.fetchone()[0]
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"🤝 Your referral link: {referral_link}\nTotal referrals: {referral_count}\nEarn 200 coins per referral!",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Error fetching referral count: {e}")
        await update.message.reply_text("An error occurred while fetching referral info.")
    finally:
        conn.close()

# /tasks command
async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await check_channel_membership(context, user.id):
        channel_link = get_setting('CHANNEL_LINK')
        keyboard = [[InlineKeyboardButton("Join Channel", url=channel_link)],
                    [InlineKeyboardButton("✅ Check Join", callback_data='check_join')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"You must join our channel to use this command: {channel_link}\nAfter joining, click 'Check Join'.",
            reply_markup=reply_markup
        )
        return
    
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT task_id, title, description, link, reward FROM tasks')
        tasks = c.fetchall()
        if not tasks:
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("No tasks available at the moment.", reply_markup=reply_markup)
            return
        message = "📋 *Available Tasks:*\n\n"
        for task in tasks:
            task_id, title, desc, link, reward = task
            message += f"*{title}* (ID: {task_id})\n{desc}\n🔗 [Click Here]({link})\n💰 Reward: {reward} coins\n📤 [Submit Proof](submit_proof:{task_id})\n\n"
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error fetching tasks: {e}")
        await update.message.reply_text("An error occurred while fetching tasks.")
    finally:
        conn.close()

# /complete_task command
async def complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await check_channel_membership(context, user.id):
        channel_link = get_setting('CHANNEL_LINK')
        keyboard = [[InlineKeyboardButton("Join Channel", url=channel_link)],
                    [InlineKeyboardButton("✅ Check Join", callback_data='check_join')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"You must join our channel to use this command: {channel_link}\nAfter joining, click 'Check Join'.",
            reply_markup=reply_markup
        )
        return
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "To complete a task:\n1. Go to /tasks and select a task.\n2. Follow the task instructions and click the link.\n3. Click '📤 Submit Proof' and upload a screenshot as proof.\n4. Wait for admin approval to receive your coins!",
        reply_markup=reply_markup
    )

# /coins command
async def coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await check_channel_membership(context, user.id):
        channel_link = get_setting('CHANNEL_LINK')
        keyboard = [[InlineKeyboardButton("Join Channel", url=channel_link)],
                    [InlineKeyboardButton("✅ Check Join", callback_data='check_join')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"You must join our channel to use this command: {channel_link}\nAfter joining, click 'Check Join'.",
            reply_markup=reply_markup
        )
        return
    user_id = user.id
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(ph('SELECT coins FROM users WHERE user_id = %s'), (user_id,))
        result = c.fetchone()
        coins = result[0] if result else 0
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"💰 Your current balance: {coins} coins", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error fetching coins: {e}")
        await update.message.reply_text("An error occurred while fetching your balance.")
    finally:
        conn.close()

# /daily command
async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await check_channel_membership(context, user.id):
        channel_link = get_setting('CHANNEL_LINK')
        keyboard = [[InlineKeyboardButton("Join Channel", url=channel_link)],
                    [InlineKeyboardButton("✅ Check Join", callback_data='check_join')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"You must join our channel to use this command: {channel_link}\nAfter joining, click 'Check Join'.",
            reply_markup=reply_markup
        )
        return
    user_id = user.id
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(ph('SELECT last_claim FROM daily_claims WHERE user_id = %s'), (user_id,))
        last_claim = c.fetchone()
        now = datetime.datetime.now()
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if last_claim and (now - datetime.datetime.fromisoformat(last_claim[0])).days < 1:
            await update.message.reply_text("You've already claimed your daily reward today. Try again tomorrow!", reply_markup=reply_markup)
            return
        c.execute(ph('UPDATE users SET coins = coins + 50 WHERE user_id = %s'), (user_id,))
        c.execute(ph('INSERT INTO daily_claims (user_id, last_claim) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET last_claim = %s'),
                  (user_id, now.isoformat(), now.isoformat()))
        conn.commit()
        await update.message.reply_text("🎁 You claimed 50 coins as your daily reward!", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error in daily command: {e}")
        await update.message.reply_text("An error occurred while claiming your daily reward.")
    finally:
        conn.close()

# /leaderboard command
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await check_channel_membership(context, user.id):
        channel_link = get_setting('CHANNEL_LINK')
        keyboard = [[InlineKeyboardButton("Join Channel", url=channel_link)],
                    [InlineKeyboardButton("✅ Check Join", callback_data='check_join')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"You must join our channel to use this command: {channel_link}\nAfter joining, click 'Check Join'.",
            reply_markup=reply_markup
        )
        return
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT username, coins FROM users ORDER BY coins DESC LIMIT 10')
        top_users = c.fetchall()
        message = "🏆 *Top 10 Coin Holders:*\n\n"
        for i, (username, coins) in enumerate(top_users, 1):
            message += f"{i}. @{username or 'Unknown'} - {coins} coins\n"
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error fetching leaderboard: {e}")
        await update.message.reply_text("An error occurred while fetching the leaderboard.")
    finally:
        conn.close()

# /top_inviters command
async def top_inviters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await check_channel_membership(context, user.id):
        channel_link = get_setting('CHANNEL_LINK')
        keyboard = [[InlineKeyboardButton("Join Channel", url=channel_link)],
                    [InlineKeyboardButton("✅ Check Join", callback_data='check_join')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"You must join our channel to use this command: {channel_link}\nAfter joining, click 'Check Join'.",
            reply_markup=reply_markup
        )
        return
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT u.username, COUNT(r.referred_id) as ref_count FROM users u '
                  'LEFT JOIN referrals r ON u.user_id = r.referrer_id '
                  'GROUP BY u.user_id, u.username ORDER BY ref_count DESC LIMIT 10')
        top_referrers = c.fetchall()
        message = "👥 *Top 10 Inviters:*\n\n"
        for i, (username, ref_count) in enumerate(top_referrers, 1):
            message += f"{i}. @{username or 'Unknown'} - {ref_count} referrals\n"
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error fetching top inviters: {e}")
        await update.message.reply_text("An error occurred while fetching top inviters.")
    finally:
        conn.close()

# /support command
async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await check_channel_membership(context, user.id):
        channel_link = get_setting('CHANNEL_LINK')
        keyboard = [[InlineKeyboardButton("Join Channel", url=channel_link)],
                    [InlineKeyboardButton("✅ Check Join", callback_data='check_join')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"You must join our channel to use this command: {channel_link}\nAfter joining, click 'Check Join'.",
            reply_markup=reply_markup
        )
        return
    support_group = get_setting('SUPPORT_GROUP')
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"📞 Need help? Join our support group: {support_group}\nOr contact an admin: {ADMIN_USERNAME}",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# /settings command
async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("🚫 You are not authorized to use this command.")
        return
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT key, value FROM settings')
        settings = c.fetchall()
        c.execute('SELECT task_id, title, description, link, reward FROM tasks')
        tasks = c.fetchall()
        message = "⚙️ *Current Settings*\n\n"
        for key, value in settings:
            message += f"{key}: {value}\n"
        message += "\n📋 *Tasks*\n"
        if tasks:
            for task in tasks:
                task_id, title, desc, link, reward = task
                message += f"ID: {task_id}, Title: {title}, Desc: {desc}, Link: {link}, Reward: {reward}\n"
        else:
            message += "No tasks available.\n"
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error fetching settings: {e}")
        await update.message.reply_text("An error occurred while fetching settings.")
    finally:
        conn.close()

# /admin command
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("🚫 You are not authorized to use this command.")
        return
    channel_link = get_setting('CHANNEL_LINK')
    support_group = get_setting('SUPPORT_GROUP')
    keyboard = [
        [InlineKeyboardButton("📢 Update Channel Link", callback_data='update_channel')],
        [InlineKeyboardButton("📞 Update Support Group", callback_data='update_support')],
        [InlineKeyboardButton("➕ Add Task", callback_data='add_task')],
        [InlineKeyboardButton("🗑️ Delete Task", callback_data='delete_task')],
        [InlineKeyboardButton("🔙 Back", callback_data='back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"🔧 *Admin Panel*\n\nCurrent Channel Link: {channel_link}\nCurrent Support Group: {support_group}\nSelect an option below:\nNote: Use /settings to view all settings or /edittask to edit tasks.",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# /edittask command
async def edit_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("🚫 You are not authorized to use this command.")
        return
    args = context.args
    if len(args) < 5:
        await update.message.reply_text(
            "Usage: /edittask <task_id> <title> | <description> | <link> | <reward>\nExample: /edittask 1 Follow Twitter | Follow @XRewardBot | https://x.com/XRewardBot | 100\nUse /settings to see task IDs."
        )
        return
    try:
        task_id = int(args[0])
        title, description, link, reward = ' '.join(args[1:]).split('|', 3)
        reward = int(reward.strip())
        if reward <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Invalid input. Task ID and reward must be numbers, and use | to separate fields.")
        return
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(ph('UPDATE tasks SET title = %s, description = %s, link = %s, reward = %s WHERE task_id = %s'),
                  (title.strip(), description.strip(), link.strip(), reward, task_id))
        if c.rowcount == 0:
            await update.message.reply_text("Task ID not found. Use /settings to check IDs.")
        else:
            await update.message.reply_text(f"✅ Task {task_id} updated successfully!")
        conn.commit()
    except Exception as e:
        logger.error(f"Error editing task: {e}")
        await update.message.reply_text("An error occurred while editing the task.")
    finally:
        conn.close()

# Conversation handler for updating channel link
async def update_channel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id not in ADMIN_IDS:
        await query.message.edit_text("🚫 You are not authorized.")
        return ConversationHandler.END
    await query.message.edit_text("Please send the new channel link (e.g., https://t.me/YourChannel).")
    return CHANNEL_LINK_STATE

async def update_channel_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_link = update.message.text.strip()
    if not new_link.startswith('https://t.me/'):
        await update.message.reply_text("Invalid link. It must start with https://t.me/. Try again.")
        return CHANNEL_LINK_STATE
    update_setting('CHANNEL_LINK', new_link)
    keyboard = [[InlineKeyboardButton("🔙 Back to Admin Panel", callback_data='admin_panel')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"✅ Channel link updated to: {new_link}", reply_markup=reply_markup)
    return ConversationHandler.END

# Conversation handler for updating support group
async def update_support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id not in ADMIN_IDS:
        await query.message.edit_text("🚫 You are not authorized.")
        return ConversationHandler.END
    await query.message.edit_text("Please send the new support group link (e.g., https://t.me/YourSupportGroup).")
    return SUPPORT_GROUP_STATE

async def update_support_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_link = update.message.text.strip()
    if not new_link.startswith('https://t.me/'):
        await update.message.reply_text("Invalid link. It must start with https://t.me/. Try again.")
        return SUPPORT_GROUP_STATE
    update_setting('SUPPORT_GROUP', new_link)
    keyboard = [[InlineKeyboardButton("🔙 Back to Admin Panel", callback_data='admin_panel')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"✅ Support group link updated to: {new_link}", reply_markup=reply_markup)
    return ConversationHandler.END

# Conversation handler for adding task
async def add_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id not in ADMIN_IDS:
        await query.message.edit_text("🚫 You are not authorized.")
        return ConversationHandler.END
    await query.message.edit_text("Please send the task title.")
    return TASK_TITLE

async def add_task_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['task_title'] = update.message.text.strip()
    await update.message.reply_text("Please send the task description.")
    return TASK_DESCRIPTION

async def add_task_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['task_description'] = update.message.text.strip()
    await update.message.reply_text("Please send the task link (e.g., https://x.com/XRewardBot).")
    return TASK_LINK

async def add_task_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.startswith('http'):
        await update.message.reply_text("Invalid link. It must start with http:// or https://. Try again.")
        return TASK_LINK
    context.user_data['task_link'] = link
    await update.message.reply_text("Please send the task reward (a number, e.g., 100).")
    return TASK_REWARD

async def add_task_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        reward = int(update.message.text.strip())
        if reward <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Invalid reward. Please send a positive number.")
        return TASK_REWARD
    title = context.user_data['task_title']
    description = context.user_data['task_description']
    link = context.user_data['task_link']
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(ph('INSERT INTO tasks (title, description, link, reward) VALUES (%s, %s, %s, %s)'),
                  (title, description, link, reward))
        conn.commit()
        keyboard = [[InlineKeyboardButton("🔙 Back to Admin Panel", callback_data='admin_panel')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"✅ Task '{title}' added successfully!", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error adding task: {e}")
        await update.message.reply_text("An error occurred while adding the task.")
    finally:
        conn.close()
        context.user_data.clear()
    return ConversationHandler.END

# /addtask command
async def add_task_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("🚫 You are not authorized to use this command.")
        return
    args = context.args
    if len(args) < 4:
        await update.message.reply_text(
            "Usage: /addtask <title> | <description> | <link> | <reward>\nExample: /addtask Follow Twitter | Follow @XRewardBot | https://x.com/XRewardBot | 100"
        )
        return
    try:
        title, description, link, reward = ' '.join(args).split('|', 3)
        reward = int(reward.strip())
        if reward <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Invalid input. Reward must be a positive number, and use | to separate fields.")
        return
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(ph('INSERT INTO tasks (title, description, link, reward) VALUES (%s, %s, %s, %s)'),
                  (title.strip(), description.strip(), link.strip(), reward))
        conn.commit()
        await update.message.reply_text(f"✅ Task '{title.strip()}' added successfully!")
    except Exception as e:
        logger.error(f"Error adding task: {e}")
        await update.message.reply_text("An error occurred while adding the task.")
    finally:
        conn.close()

# /deletetask command
async def delete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("🚫 You are not authorized to use this command.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /deletetask <task_id>\nUse /settings to see task IDs.")
        return
    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Task ID must be a number.")
        return
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(ph('DELETE FROM tasks WHERE task_id = %s'), (task_id,))
        if c.rowcount == 0:
            await update.message.reply_text("Task not found.")
        else:
            await update.message.reply_text(f"✅ Task {task_id} deleted.")
        conn.commit()
    except Exception as e:
        logger.error(f"Error deleting task: {e}")
        await update.message.reply_text("An error occurred while deleting the task.")
    finally:
        conn.close()

# Handle inline button clicks
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user

    async def show_main_menu():
        keyboard = [
            [InlineKeyboardButton("📋 Tasks", callback_data='tasks'), InlineKeyboardButton("💰 Coins", callback_data='coins')],
            [InlineKeyboardButton("🎁 Daily Reward", callback_data='daily'), InlineKeyboardButton("🤝 Refer", callback_data='refer')],
            [InlineKeyboardButton("🏆 Leaderboard", callback_data='leaderboard'), InlineKeyboardButton("👥 Top Inviters", callback_data='top_inviters')],
            [InlineKeyboardButton("📞 Support", callback_data='support'), InlineKeyboardButton("🔙 Back", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            f"Welcome back, {user.first_name}! 🎉\nUse the buttons below to explore the bot.",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

    async def show_admin_panel():
        channel_link = get_setting('CHANNEL_LINK')
        support_group = get_setting('SUPPORT_GROUP')
        keyboard = [
            [InlineKeyboardButton("📢 Update Channel Link", callback_data='update_channel')],
            [InlineKeyboardButton("📞 Update Support Group", callback_data='update_support')],
            [InlineKeyboardButton("➕ Add Task", callback_data='add_task')],
            [InlineKeyboardButton("🗑️ Delete Task", callback_data='delete_task')],
            [InlineKeyboardButton("🔙 Back", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            f"🔧 *Admin Panel*\n\nCurrent Channel Link: {channel_link}\nCurrent Support Group: {support_group}\nSelect an option below:\nNote: Use /settings to view all settings or /edittask to edit tasks.",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

    if data == 'check_join':
        if await check_channel_membership(context, user.id):
            conn = get_db()
            try:
                c = conn.cursor()
                c.execute(ph('SELECT * FROM users WHERE user_id = %s'), (user.id,))
                if not c.fetchone():
                    c.execute(ph('INSERT INTO users (user_id, username, coins, joined_at) VALUES (%s, %s, %s, %s)'),
                              (user.id, user.username or 'Unknown', 100, datetime.datetime.now()))
                    conn.commit()
                await show_main_menu()
            except Exception as e:
                logger.error(f"Error in check_join: {e}")
                await query.message.edit_text("An error occurred. Please try again.")
            finally:
                conn.close()
        else:
            channel_link = get_setting('CHANNEL_LINK')
            keyboard = [[InlineKeyboardButton("Join Channel", url=channel_link)],
                        [InlineKeyboardButton("✅ Check Join", callback_data='check_join')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(
                f"You haven't joined the channel yet. Please join: {channel_link}\nThen click 'Check Join'.",
                reply_markup=reply_markup
            )
    elif data == 'back':
        await show_main_menu()
    elif data == 'admin_panel':
        if user.id not in ADMIN_IDS:
            await query.message.edit_text("🚫 You are not authorized.")
            return
        await show_admin_panel()
    elif data == 'tasks':
        if not await check_channel_membership(context, user.id):
            channel_link = get_setting('CHANNEL_LINK')
            keyboard = [[InlineKeyboardButton("Join Channel", url=channel_link)],
                        [InlineKeyboardButton("✅ Check Join", callback_data='check_join')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(
                f"You must join our channel to view tasks: {channel_link}\nAfter joining, click 'Check Join'.",
                reply_markup=reply_markup
            )
            return
        conn = get_db()
        try:
            c = conn.cursor()
            c.execute('SELECT task_id, title, description, link, reward FROM tasks')
            tasks = c.fetchall()
            message = "📋 *Available Tasks:*\n\n"
            for task in tasks:
                task_id, title, desc, link, reward = task
                message += f"*{title}* (ID: {task_id})\n{desc}\n🔗 [Click Here]({link})\n💰 Reward: {reward} coins\n📤 [Submit Proof](submit_proof:{task_id})\n\n"
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        except Exception as e:
            logger.error(f"Error in tasks button: {e}")
            await query.message.edit_text("An error occurred while fetching tasks.")
        finally:
            conn.close()
    elif data == 'coins':
        if not await check_channel_membership(context, user.id):
            channel_link = get_setting('CHANNEL_LINK')
            keyboard = [[InlineKeyboardButton("Join Channel", url=channel_link)],
                        [InlineKeyboardButton("✅ Check Join", callback_data='check_join')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(
                f"You must join our channel to view coins: {channel_link}\nAfter joining, click 'Check Join'.",
                reply_markup=reply_markup
            )
            return
        user_id = user.id
        conn = get_db()
        try:
            c = conn.cursor()
            c.execute(ph('SELECT coins FROM users WHERE user_id = %s'), (user_id,))
            coins = c.fetchone()[0]
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(f"💰 Your current balance: {coins} coins", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Error in coins button: {e}")
            await query.message.edit_text("An error occurred while fetching your balance.")
        finally:
            conn.close()
    elif data == 'daily':
        if not await check_channel_membership(context, user.id):
            channel_link = get_setting('CHANNEL_LINK')
            keyboard = [[InlineKeyboardButton("Join Channel", url=channel_link)],
                        [InlineKeyboardButton("✅ Check Join", callback_data='check_join')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(
                f"You must join our channel to claim daily rewards: {channel_link}\nAfter joining, click 'Check Join'.",
                reply_markup=reply_markup
            )
            return
        user_id = user.id
        conn = get_db()
        try:
            c = conn.cursor()
            c.execute(ph('SELECT last_claim FROM daily_claims WHERE user_id = %s'), (user_id,))
            last_claim = c.fetchone()
            now = datetime.datetime.now()
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            if last_claim and (now - datetime.datetime.fromisoformat(last_claim[0])).days < 1:
                await query.message.edit_text("You've already claimed your daily reward today. Try again tomorrow!", reply_markup=reply_markup)
            else:
                c.execute(ph('UPDATE users SET coins = coins + 50 WHERE user_id = %s'), (user_id,))
                c.execute(ph('INSERT INTO daily_claims (user_id, last_claim) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET last_claim = %s'),
                          (user_id, now.isoformat(), now.isoformat()))
                conn.commit()
                await query.message.edit_text("🎁 You claimed 50 coins as your daily reward!", reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error in daily button: {e}")
            await query.message.edit_text("An error occurred while claiming your daily reward.")
        finally:
            conn.close()
    elif data == 'refer':
        if not await check_channel_membership(context, user.id):
            channel_link = get_setting('CHANNEL_LINK')
            keyboard = [[InlineKeyboardButton("Join Channel", url=channel_link)],
                        [InlineKeyboardButton("✅ Check Join", callback_data='check_join')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(
                f"You must join our channel to view referral info: {channel_link}\nAfter joining, click 'Check Join'.",
                reply_markup=reply_markup
            )
            return
        user_id = user.id
        bot_username = context.bot.username
    referral_link = f"https://t.me/{bot_username}?start={user_id}"
        conn = get_db()
        try:
            c = conn.cursor()
            c.execute(ph('SELECT COUNT(*) FROM referrals WHERE referrer_id = %s'), (user_id,))
            referral_count = c.fetchone()[0]
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(
                f"🤝 Your referral link: {referral_link}\nTotal referrals: {referral_count}\nEarn 200 coins per referral!",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error in refer button: {e}")
            await query.message.edit_text("An error occurred while fetching referral info.")
        finally:
            conn.close()
    elif data == 'leaderboard':
        if not await check_channel_membership(context, user.id):
            channel_link = get_setting('CHANNEL_LINK')
            keyboard = [[InlineKeyboardButton("Join Channel", url=channel_link)],
                        [InlineKeyboardButton("✅ Check Join", callback_data='check_join')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(
                f"You must join our channel to view leaderboard: {channel_link}\nAfter joining, click 'Check Join'.",
                reply_markup=reply_markup
            )
            return
        conn = get_db()
        try:
            c = conn.cursor()
            c.execute('SELECT username, coins FROM users ORDER BY coins DESC LIMIT 10')
            top_users = c.fetchall()
            message = "🏆 *Top 10 Coin Holders:*\n\n"
            for i, (username, coins) in enumerate(top_users, 1):
                message += f"{i}. @{username or 'Unknown'} - {coins} coins\n"
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Error in leaderboard button: {e}")
            await query.message.edit_text("An error occurred while fetching the leaderboard.")
        finally:
            conn.close()
    elif data == 'top_inviters':
        if not await check_channel_membership(context, user.id):
            channel_link = get_setting('CHANNEL_LINK')
            keyboard = [[InlineKeyboardButton("Join Channel", url=channel_link)],
                        [InlineKeyboardButton("✅ Check Join", callback_data='check_join')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(
                f"You must join our channel to view top inviters: {channel_link}\nAfter joining, click 'Check Join'.",
                reply_markup=reply_markup
            )
            return
        conn = get_db()
        try:
            c = conn.cursor()
            c.execute('SELECT u.username, COUNT(r.referred_id) as ref_count FROM users u '
                      'LEFT JOIN referrals r ON u.user_id = r.referrer_id '
                      'GROUP BY u.user_id, u.username ORDER BY ref_count DESC LIMIT 10')
            top_referrers = c.fetchall()
            message = "👥 *Top 10 Inviters:*\n\n"
            for i, (username, ref_count) in enumerate(top_referrers, 1):
                message += f"{i}. @{username or 'Unknown'} - {ref_count} referrals\n"
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Error in top_inviters button: {e}")
            await query.message.edit_text("An error occurred while fetching top inviters.")
        finally:
            conn.close()
    elif data == 'support':
        if not await check_channel_membership(context, user.id):
            channel_link = get_setting('CHANNEL_LINK')
            keyboard = [[InlineKeyboardButton("Join Channel", url=channel_link)],
                        [InlineKeyboardButton("✅ Check Join", callback_data='check_join')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(
                f"You must join our channel to view support info: {channel_link}\nAfter joining, click 'Check Join'.",
                reply_markup=reply_markup
            )
            return
        support_group = get_setting('SUPPORT_GROUP')
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            f"📞 Need help? Join our support group: {support_group}\nOr contact an admin: {ADMIN_USERNAME}",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    elif data == 'update_channel':
        if user.id not in ADMIN_IDS:
            await query.message.edit_text("🚫 You are not authorized.")
            return
        await update_channel_start(update, context)
    elif data == 'update_support':
        if user.id not in ADMIN_IDS:
            await query.message.edit_text("🚫 You are not authorized.")
            return
        await update_support_start(update, context)
    elif data == 'add_task':
        if user.id not in ADMIN_IDS:
            await query.message.edit_text("🚫 You are not authorized.")
            return
        await add_task_start(update, context)
    elif data == 'delete_task':
        if user.id not in ADMIN_IDS:
            await query.message.edit_text("🚫 You are not authorized.")
            return
        conn = get_db()
        try:
            c = conn.cursor()
            c.execute('SELECT task_id, title FROM tasks')
            tasks = c.fetchall()
            if not tasks:
                await query.message.edit_text("No tasks available to delete.")
                return
            keyboard = [[InlineKeyboardButton(f"Delete Task {task[0]}: {task[1]}", callback_data=f'delete_task:{task[0]}')] for task in tasks]
            keyboard.append([InlineKeyboardButton("🔙 Back to Admin Panel", callback_data='admin_panel')])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text("Select a task to delete:", reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error fetching tasks for deletion: {e}")
            await query.message.edit_text("An error occurred while fetching tasks.")
        finally:
            conn.close()
    elif data.startswith('delete_task:'):
        if user.id not in ADMIN_IDS:
            await query.message.edit_text("🚫 You are not authorized.")
            return
        task_id = int(data.split(':')[1])
        conn = get_db()
        try:
            c = conn.cursor()
            c.execute(ph('DELETE FROM tasks WHERE task_id = %s'), (task_id,))
            if c.rowcount == 0:
                await query.message.edit_text("Task not found.")
            else:
                await query.message.edit_text(f"✅ Task {task_id} deleted.")
            conn.commit()
        except Exception as e:
            logger.error(f"Error deleting task: {e}")
            await query.message.edit_text("An error occurred while deleting the task.")
        finally:
            conn.close()
    elif data == 'admin_panel':
        if user.id not in ADMIN_IDS:
            await query.message.edit_text("🚫 You are not authorized.")
            return
        await show_admin_panel()

# Cancel conversation
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled. Use /start to continue.")
    return ConversationHandler.END

def main():
    init_db()
    logger.info(f"Starting application with BOT_TOKEN: {BOT_TOKEN[:10]}...")  # Log partial token for debugging
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Register handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('refer', refer))
    application.add_handler(CommandHandler('tasks', tasks))
    application.add_handler(CommandHandler('complete_task', complete_task))
    application.add_handler(CommandHandler('coins', coins))
    application.add_handler(CommandHandler('daily', daily))
    application.add_handler(CommandHandler('leaderboard', leaderboard))
    application.add_handler(CommandHandler('top_inviters', top_inviters))
    application.add_handler(CommandHandler('support', support))
    application.add_handler(CommandHandler('settings', settings))
    application.add_handler(CommandHandler('admin', admin))
    application.add_handler(CommandHandler('addtask', add_task_cmd))
    application.add_handler(CommandHandler('edittask', edit_task))
    application.add_handler(CommandHandler('deletetask', delete_task))
    
    # Conversation handlers
    channel_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(update_channel_start, pattern='^update_channel$')],
        states={CHANNEL_LINK_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, update_channel_receive)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    support_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(update_support_start, pattern='^update_support$')],
        states={SUPPORT_GROUP_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, update_support_receive)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    task_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_task_start, pattern='^add_task$')],
        states={
            TASK_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_title)],
            TASK_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_description)],
            TASK_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_link)],
            TASK_REWARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_reward)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    application.add_handler(channel_conv)
    application.add_handler(support_conv)
    application.add_handler(task_conv)
    application.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info("Bot is starting...")
    application.run_polling()

if __name__ == '__main__':
    main()
