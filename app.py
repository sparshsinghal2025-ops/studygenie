"""
StudyGenie Bot - Vercel Production Ready
Author: Sparsh Singhal
Version: 6.0.0 - Vercel Optimized
"""

import os
import json
import time
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify

# Telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters, Defaults
)
from telegram.constants import ParseMode, ChatAction

# Database (Upstash Redis for serverless)
import redis

# AI
from google import genai
from google.genai import types as genai_types

# Load environment
from dotenv import load_dotenv
load_dotenv()

# ============================================================================
# CONFIGURATION
# ============================================================================

IST = ZoneInfo("Asia/Kolkata")

def _today_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")

class Config:
    """Vercel Configuration"""
    
    def __init__(self):
        # Bot
        self.BOT_TOKEN = os.getenv('BOT_TOKEN', '')
        
        # Vercel URL (required for webhook)
        self.VERCEL_URL = os.getenv('VERCEL_URL', '')  # Auto-set by Vercel
        
        # Upstash Redis (Serverless Redis)
        self.REDIS_URL = os.getenv('REDIS_URL', os.getenv('UPSTASH_REDIS_URL', ''))
        
        # Google AI
        self.GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY', '')
        self.GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
        self.GEMINI_TIMEOUT = int(os.getenv('GEMINI_TIMEOUT', '10'))
        
        # Quota
        self.FREE_DAILY_QUESTIONS = int(os.getenv('FREE_DAILY_QUESTIONS', '10'))
        self.FREE_LIFETIME_QUESTIONS = int(os.getenv('FREE_LIFETIME_QUESTIONS', '30'))
        self.PRO_PRICE_INR = int(os.getenv('PRO_PRICE_INR', '49'))
        
        # Gamification
        self.XP_PER_QUESTION = int(os.getenv('XP_PER_QUESTION', '12'))
        self.XP_PER_QUIZ = int(os.getenv('XP_PER_QUIZ', '20'))
        
        # Cache
        self.CACHE_ENABLED = os.getenv('CACHE_ENABLED', '1') == '1'
        self.CACHE_TTL = int(os.getenv('CACHE_TTL', '3600'))
        
        self.validate()
    
    def validate(self):
        if not self.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is required")
        if not self.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY is required")

config = Config()

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# REDIS (Upstash for Serverless)
# ============================================================================

class Database:
    """Serverless Database with Upstash Redis"""
    
    def __init__(self):
        self.redis = self._init_redis()
    
    def _init_redis(self):
        """Initialize Upstash Redis"""
        if not config.REDIS_URL:
            logger.warning("Redis URL not set. Using in-memory fallback.")
            return None
        
        try:
            client = redis.from_url(
                config.REDIS_URL,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
                retry_on_timeout=True
            )
            client.ping()
            logger.info("✅ Redis connected")
            return client
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            return None
    
    # User operations
    def get_user(self, user_id: int) -> Optional[Dict]:
        """Get user data"""
        if not self.redis:
            return None
        
        try:
            data = self.redis.hgetall(f"user:{user_id}")
            return data if data else None
        except Exception as e:
            logger.error(f"Failed to get user: {e}")
            return None
    
    def save_user(self, user_id: int, data: Dict) -> bool:
        """Save user data"""
        if not self.redis:
            return False
        
        try:
            redis_data = {k: str(v) for k, v in data.items()}
            self.redis.hset(f"user:{user_id}", mapping=redis_data)
            self.redis.expire(f"user:{user_id}", 86400 * 30)  # 30 days
            return True
        except Exception as e:
            logger.error(f"Failed to save user: {e}")
            return False
    
    def is_registered(self, user_id: int) -> bool:
        """Check if user registered"""
        return self.get_user(user_id) is not None
    
    def add_xp(self, user_id: int, amount: int) -> int:
        """Add XP"""
        user = self.get_user(user_id)
        if not user:
            return 0
        
        new_xp = int(user.get('xp', 0)) + amount
        user['xp'] = new_xp
        self.save_user(user_id, user)
        
        # Update leaderboard
        if self.redis:
            try:
                self.redis.zadd('leaderboard', {str(user_id): new_xp})
            except:
                pass
        
        return new_xp
    
    def update_streak(self, user_id: int) -> Dict:
        """Update streak"""
        user = self.get_user(user_id)
        if not user:
            return {'current': 0, 'best': 0, 'shields': 0}
        
        today = _today_ist()
        last_activity = str(user.get('last_activity', ''))
        
        if last_activity == today:
            return {
                'current': int(user.get('streak', 0)),
                'best': int(user.get('best_streak', 0)),
                'shields': int(user.get('shields', 0))
            }
        
        yesterday = (datetime.now(IST) - timedelta(days=1)).strftime("%Y-%m-%d")
        current_streak = int(user.get('streak', 0))
        shields = int(user.get('shields', 0))
        
        if last_activity == yesterday:
            new_streak = current_streak + 1
        elif shields > 0:
            new_streak = current_streak + 1
            shields -= 1
        else:
            new_streak = 1
        
        if new_streak > 0 and new_streak % 7 == 0:
            shields += 1
        
        best_streak = max(new_streak, int(user.get('best_streak', 0)))
        
        user.update({
            'streak': new_streak,
            'best_streak': best_streak,
            'shields': shields,
            'last_activity': today
        })
        self.save_user(user_id, user)
        
        return {'current': new_streak, 'best': best_streak, 'shields': shields}
    
    def check_quota(self, user_id: int) -> Tuple[bool, Dict]:
        """Check quota"""
        user = self.get_user(user_id)
        if not user:
            return False, {'daily_left': 0, 'lifetime_left': 0}
        
        # Pro users unlimited
        if user.get('plan') == 'pro':
            return True, {'daily_left': -1, 'lifetime_left': -1}
        
        if self.redis:
            try:
                today = _today_ist()
                daily_key = f"quota:daily:{user_id}:{today}"
                lifetime_key = f"quota:lifetime:{user_id}"
                
                daily_used = int(self.redis.get(daily_key) or 0)
                lifetime_used = int(self.redis.get(lifetime_key) or 0)
                
                daily_left = max(0, config.FREE_DAILY_QUESTIONS - daily_used)
                lifetime_left = max(0, config.FREE_LIFETIME_QUESTIONS - lifetime_used)
                
                return (daily_left > 0 and lifetime_left > 0), {
                    'daily_left': daily_left,
                    'lifetime_left': lifetime_left
                }
            except:
                pass
        
        return True, {
            'daily_left': config.FREE_DAILY_QUESTIONS,
            'lifetime_left': config.FREE_LIFETIME_QUESTIONS
        }
    
    def consume_quota(self, user_id: int) -> bool:
        """Consume quota"""
        if self.redis:
            try:
                today = _today_ist()
                daily_key = f"quota:daily:{user_id}:{today}"
                lifetime_key = f"quota:lifetime:{user_id}"
                
                self.redis.incr(daily_key)
                self.redis.expire(daily_key, 86400)
                self.redis.incr(lifetime_key)
                return True
            except:
                pass
        
        return True
    
    def get_leaderboard(self, user_id: int, limit: int = 10) -> List:
        """Get leaderboard"""
        if not self.redis:
            return []
        
        try:
            top = self.redis.zrevrange('leaderboard', 0, limit - 1, withscores=True)
            leaderboard = []
            
            for rank, (uid, xp) in enumerate(top, 1):
                user = self.get_user(int(uid))
                if user:
                    leaderboard.append({
                        'rank': rank,
                        'user_id': int(uid),
                        'name': user.get('full_name', 'Unknown'),
                        'xp': int(xp)
                    })
            
            return leaderboard
        except:
            return []

db = Database()

# ============================================================================
# AI SERVICE
# ============================================================================

class AIService:
    """Fast AI Service with caching"""
    
    def __init__(self):
        self.client = self._init_client()
        self.cache = {}
    
    def _init_client(self):
        """Initialize Gemini"""
        if not config.GOOGLE_API_KEY:
            return None
        
        try:
            client = genai.Client(api_key=config.GOOGLE_API_KEY)
            logger.info("✅ Gemini initialized")
            return client
        except Exception as e:
            logger.error(f"❌ Gemini init failed: {e}")
            return None
    
    def answer_question(self, question: str, tool: str = 'general') -> Optional[str]:
        """Generate answer with caching"""
        if not self.client:
            return "AI service unavailable. Please try again later."
        
        # Check cache
        cache_key = f"{tool}:{question.lower().strip()}"
        if config.CACHE_ENABLED and cache_key in self.cache:
            logger.info("⚡ Cache hit!")
            return self.cache[cache_key]
        
        # Build prompt
        prompt = self._build_prompt(question, tool)
        
        try:
            start_time = time.time()
            response = self.client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=[prompt]
            )
            
            duration = time.time() - start_time
            logger.info(f"⚡ Generated in {duration:.2f}s")
            
            answer = response.text
            
            # Cache
            if config.CACHE_ENABLED:
                self.cache[cache_key] = answer
                if len(self.cache) > 500:
                    for key in list(self.cache.keys())[:50]:
                        del self.cache[key]
            
            return answer
        except Exception as e:
            logger.error(f"Gemini failed: {e}")
            return None
    
    def _build_prompt(self, question: str, tool: str) -> str:
        """Build prompt"""
        base = (
            "You are StudyGenie, expert AI tutor for Indian students (JEE, NEET, GATE, Boards). "
            "Answer in Hinglish. Be encouraging, use emojis, explain step-by-step.\n\n"
        )
        
        prompts = {
            'general': f"{base}Question: {question}",
            'explain': f"{base}Explain simply with examples.\n\nConcept: {question}",
            'solve': f"{base}Solve step-by-step.\n\nProblem: {question}",
            'notes': f"{base}Create concise notes.\n\nTopic: {question}",
            'pyq': f"{base}Solve this PYQ.\n\nQuestion: {question}",
            'formula': f"{base}List formulas.\n\nTopic: {question}",
        }
        
        return prompts.get(tool, prompts['general'])

ai_service = AIService()

# ============================================================================
# KEYBOARDS
# ============================================================================

class Keyboards:
    """Keyboard builders"""
    
    @staticmethod
    def main_menu() -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton("📚 Ask Question", callback_data="menu_ask"),
             InlineKeyboardButton("🎯 Quiz", callback_data="menu_quiz")],
            [InlineKeyboardButton("📖 Study Tools", callback_data="menu_tools"),
             InlineKeyboardButton("📊 Progress", callback_data="menu_progress")],
            [InlineKeyboardButton("🏆 Leaderboard", callback_data="menu_leaderboard"),
             InlineKeyboardButton("🔥 Streak", callback_data="menu_streak")],
            [InlineKeyboardButton("💎 Upgrade", callback_data="menu_upgrade")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def tools_menu() -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton("💡 Explain", callback_data="tool_explain"),
             InlineKeyboardButton("🧮 Solve", callback_data="tool_solve")],
            [InlineKeyboardButton("📝 Notes", callback_data="tool_notes"),
             InlineKeyboardButton("📋 PYQ", callback_data="tool_pyq")],
            [InlineKeyboardButton("📐 Formulas", callback_data="tool_formula"),
             InlineKeyboardButton("🔙 Back", callback_data="menu_main")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def quiz_options() -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton("A", callback_data="quiz_A"),
             InlineKeyboardButton("B", callback_data="quiz_B")],
            [InlineKeyboardButton("C", callback_data="quiz_C"),
             InlineKeyboardButton("D", callback_data="quiz_D")],
            [InlineKeyboardButton("❌ Stop", callback_data="quiz_stop")]
        ]
        return InlineKeyboardMarkup(keyboard)

keyboards = Keyboards()

# ============================================================================
# FLASK APP (Vercel Serverless)
# ============================================================================

app = Flask(__name__)

# Telegram Bot Application
telegram_app = None

async def setup_bot():
    """Setup Telegram bot"""
    global telegram_app
    
    if telegram_app:
        return telegram_app
    
    defaults = Defaults(parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    
    telegram_app = ApplicationBuilder()\
        .token(config.BOT_TOKEN)\
        .defaults(defaults)\
        .connect_timeout(10)\
        .read_timeout(20)\
        .write_timeout(20)\
        .build()
    
    # Register handlers
    register_handlers()
    
    # Set webhook
    if config.VERCEL_URL:
        webhook_url = f"https://{config.VERCEL_URL}/api/webhook"
        await telegram_app.bot.set_webhook(url=webhook_url)
        logger.info(f"✅ Webhook set to: {webhook_url}")
    
    await telegram_app.initialize()
    
    return telegram_app

def register_handlers():
    """Register all handlers"""
    
    # Commands
    telegram_app.add_handler(CommandHandler("start", start_command))
    telegram_app.add_handler(CommandHandler("menu", menu_command))
    telegram_app.add_handler(CommandHandler("ask", ask_command))
    telegram_app.add_handler(CommandHandler("explain", explain_command))
    telegram_app.add_handler(CommandHandler("solve", solve_command))
    telegram_app.add_handler(CommandHandler("notes", notes_command))
    telegram_app.add_handler(CommandHandler("pyq", pyq_command))
    telegram_app.add_handler(CommandHandler("formula", formula_command))
    telegram_app.add_handler(CommandHandler("quiz", quiz_command))
    telegram_app.add_handler(CommandHandler("progress", progress_command))
    telegram_app.add_handler(CommandHandler("streak", streak_command))
    telegram_app.add_handler(CommandHandler("leaderboard", leaderboard_command))
    telegram_app.add_handler(CommandHandler("upgrade", upgrade_command))
    
    # Callback
    telegram_app.add_handler(CallbackQueryHandler(callback_handler))
    
    # Free text
    telegram_app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        free_text_handler
    ))
    
    # Error
    telegram_app.add_error_handler(error_handler)

# ============================================================================
# HANDLERS
# ============================================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    user_id = update.effective_user.id
    
    if db.is_registered(user_id):
        await menu_command(update, context)
        return
    
    # Auto-register
    user_data = {
        'user_id': user_id,
        'username': update.effective_user.username or '',
        'full_name': update.effective_user.full_name or 'Student',
        'phone': '',
        'plan': 'free',
        'xp': 0,
        'streak': 0,
        'shields': 0,
        'subject': 'general',
        'grade': 'other',
        'questions_asked': 0,
        'quizzes_taken': 0,
        'correct_answers': 0,
        'last_activity': _today_ist()
    }
    db.save_user(user_id, user_data)
    
    await update.message.reply_text(
        f"🎓 *Welcome to StudyGenie, {user_data['full_name']}!*\n\n"
        f"Your AI tutor for JEE, NEET, GATE & Boards.\n\n"
        f"🎁 You have:\n"
        f"• {config.FREE_DAILY_QUESTIONS} free questions daily\n"
        f"• {config.FREE_LIFETIME_QUESTIONS} free lifetime questions\n\n"
        f"Just type your question to get instant answer!\n"
        f"Or use /menu for all options."
    )
    
    await menu_command(update, context)

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show menu"""
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    
    if not user:
        await start_command(update, context)
        return
    
    # Update streak
    streak_data = db.update_streak(user_id)
    
    is_pro = user.get('plan') == 'pro'
    quota = db.check_quota(user_id)
    
    message = (
        f"🎓 *StudyGenie*\n\n"
        f"👤 {user.get('full_name', 'Student')}\n"
        f"⭐ XP: {user.get('xp', 0)}\n"
        f"🔥 Streak: {streak_data['current']} days\n"
    )
    
    if is_pro:
        message += "\n💎 *PRO Member*\n"
    else:
        message += f"\n❓ Questions left: {quota[1].get('daily_left', 0)}\n"
    
    message += "\n*Choose option:*"
    
    await update.message.reply_text(message, reply_markup=keyboards.main_menu())

async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask question"""
    question = ' '.join(context.args) if context.args else ''
    if question:
        await process_question(update, context, question, 'general')
    else:
        await update.message.reply_text(
            "📚 Usage: /ask <question>\n\n"
            "Or just type your question directly!"
        )

async def explain_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = ' '.join(context.args) if context.args else ''
    if topic:
        await process_question(update, context, topic, 'explain')

async def solve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    problem = ' '.join(context.args) if context.args else ''
    if problem:
        await process_question(update, context, problem, 'solve')

async def notes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = ' '.join(context.args) if context.args else ''
    if topic:
        await process_question(update, context, topic, 'notes')

async def pyq_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = ' '.join(context.args) if context.args else ''
    if question:
        await process_question(update, context, question, 'pyq')

async def formula_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = ' '.join(context.args) if context.args else ''
    if topic:
        await process_question(update, context, topic, 'formula')

async def free_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle free text - auto detect"""
    text = update.message.text.strip()
    
    # Auto-detect intent
    lower = text.lower()
    if lower.startswith(('explain', 'what is', 'why', 'how')):
        tool = 'explain'
    elif lower.startswith(('solve', 'calculate', 'find')):
        tool = 'solve'
    elif lower.startswith(('notes', 'summarize')):
        tool = 'notes'
    else:
        tool = 'general'
    
    await process_question(update, context, text, tool)

async def process_question(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                          question: str, tool: str = 'general'):
    """Process question"""
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    
    if not user:
        await start_command(update, context)
        return
    
    # Check quota
    if user.get('plan') != 'pro':
        can_ask, quota = db.check_quota(user_id)
        if not can_ask:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 Upgrade", callback_data="menu_upgrade")]
            ])
            await update.message.reply_text(
                "❌ *Daily quota exceeded!*\n"
                "Upgrade to Pro for unlimited access!",
                reply_markup=keyboard
            )
            return
    
    # Show typing
    await update.message.chat.send_action(ChatAction.TYPING)
    
    # Generate answer
    start_time = time.time()
    answer = ai_service.answer_question(question, tool)
    response_time = time.time() - start_time
    
    if not answer:
        await update.message.reply_text(
            "😔 Sorry, I'm having trouble. Please try again."
        )
        return
    
    # Consume quota and add XP
    if user.get('plan') != 'pro':
        db.consume_quota(user_id)
    
    xp_awarded = config.XP_PER_QUESTION
    db.add_xp(user_id, xp_awarded)
    
    # Update stats
    user['questions_asked'] = int(user.get('questions_asked', 0)) + 1
    db.save_user(user_id, user)
    
    # Send answer
    message = (
        f"{answer}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"⚡ {response_time:.1f}s | ⭐ +{xp_awarded} XP"
    )
    
    if len(message) > 4096:
        parts = [message[i:i+4000] for i in range(0, len(message), 4000)]
        for part in parts:
            await update.message.reply_text(part)
    else:
        await update.message.reply_text(message)

async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start quiz"""
    await update.message.reply_text(
        "🎯 *Quiz*\n\n"
        "Quiz feature coming soon!\n"
        "For now, you can ask any question and get instant answers."
    )

async def progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show progress"""
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    
    if not user:
        await start_command(update, context)
        return
    
    xp = int(user.get('xp', 0))
    level = (xp // 100) + 1
    xp_in_level = xp % 100
    
    bar_length = 10
    filled = int(xp_in_level / 100 * bar_length)
    bar = "█" * filled + "░" * (bar_length - filled)
    
    message = (
        f"📊 *Progress*\n\n"
        f"⭐ Level: {level}\n"
        f"📈 XP: {xp}\n"
        f"{bar} {xp_in_level}/100\n\n"
        f"🔥 Streak: {user.get('streak', 0)} days\n"
        f"📚 Questions: {user.get('questions_asked', 0)}\n"
    )
    
    await update.message.reply_text(message)

async def streak_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show streak"""
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    
    if not user:
        await start_command(update, context)
        return
    
    message = (
        f"🔥 *Streak*\n\n"
        f"Current: {user.get('streak', 0)} days\n"
        f"Best: {user.get('best_streak', 0)} days\n"
        f"Shields: {user.get('shields', 0)}\n"
    )
    
    await update.message.reply_text(message)

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show leaderboard"""
    user_id = update.effective_user.id
    leaderboard = db.get_leaderboard(user_id)
    
    if not leaderboard:
        message = "🏆 *Leaderboard*\n\nNo data yet!"
    else:
        message = "🏆 *Top Students*\n\n"
        for entry in leaderboard[:10]:
            medal = "🥇" if entry['rank'] == 1 else "🥈" if entry['rank'] == 2 else "🥉" if entry['rank'] == 3 else f"{entry['rank']}."
            message += f"{medal} {entry['name']}: {entry['xp']} XP\n"
    
    await update.message.reply_text(message)

async def upgrade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Upgrade"""
    await update.message.reply_text(
        f"💎 *Upgrade to Pro*\n\n"
        f"• Unlimited questions\n"
        f"• All study tools\n"
        f"• Priority responses\n\n"
        f"Price: ₹{config.PRO_PRICE_INR}/month\n\n"
        f"Contact: @YourAdminUsername"
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callbacks"""
    query = update.callback_query
    data = query.data
    await query.answer()
    
    if data == "menu_main":
        await menu_command(update, context)
    elif data == "menu_ask":
        await query.edit_message_text(
            "📚 Just type your question directly!\n\n"
            "Or use /ask <question>"
        )
    elif data == "menu_quiz":
        await quiz_command(update, context)
    elif data == "menu_tools":
        await query.edit_message_text(
            "📖 *Study Tools*\n\n"
            "Select a tool:",
            reply_markup=keyboards.tools_menu()
        )
    elif data == "menu_progress":
        await progress_command(update, context)
    elif data == "menu_leaderboard":
        await leaderboard_command(update, context)
    elif data == "menu_streak":
        await streak_command(update, context)
    elif data == "menu_upgrade":
        await upgrade_command(update, context)
    elif data.startswith("tool_"):
        tool = data.replace("tool_", "")
        await query.edit_message_text(
            f"✅ *{tool.title()} selected*\n\n"
            f"Type your question directly!"
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Error handler"""
    logger.error(f"Update {update} caused error {context.error}")

# ============================================================================
# VERCEL SERVERLESS ROUTES
# ============================================================================

@app.route('/')
def home():
    """Home page"""
    return jsonify({
        'ok': True,
        'bot': 'StudyGenie',
        'status': 'running',
        'version': '6.0.0-vercel'
    })

@app.route('/api/webhook', methods=['POST'])
async def webhook():
    """Telegram webhook endpoint"""
    global telegram_app
    
    try:
        if not telegram_app:
            await setup_bot()
        
        update = Update.de_json(request.get_json(force=True), telegram_app.bot)
        await telegram_app.process_update(update)
        return jsonify({'ok': True})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/setup', methods=['GET'])
async def setup_webhook():
    """Setup webhook manually"""
    try:
        if not telegram_app:
            await setup_bot()
        
        if config.VERCEL_URL:
            webhook_url = f"https://{config.VERCEL_URL}/api/webhook"
            await telegram_app.bot.set_webhook(url=webhook_url)
            return jsonify({'ok': True, 'webhook': webhook_url})
        else:
            return jsonify({'ok': False, 'error': 'VERCEL_URL not set'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/health')
def health():
    """Health check"""
    return jsonify({
        'ok': True,
        'redis': db.redis is not None,
        'gemini': ai_service.client is not None,
        'timestamp': time.time()
    })

# ============================================================================
# VERCEL HANDLER
# ============================================================================

# For local development
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
