"""
StudyGenie Bot - Production-Ready E-Learning Bot for Telegram
Author: Sparsh Singhal
Version: 5.0.0 - Optimized for Speed
Features: Instant AI answers, quizzes, progress tracking, gamification
"""

import os
import json
import time
import asyncio
import logging
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from zoneinfo import ZoneInfo
from functools import wraps

# Core imports
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    BotCommand
)
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters,
    Defaults
)
from telegram.constants import ParseMode, ChatAction

# Database
import redis
from sqlalchemy import (
    create_engine, Column, String, Integer, DateTime, Boolean,
    Float, Text, Index
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB

# AI
from google import genai
from google.genai import types as genai_types

# Utilities
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============================================================================
# CONFIGURATION
# ============================================================================

IST = ZoneInfo("Asia/Kolkata")

def _now_ist() -> datetime:
    return datetime.now(IST)

def _today_ist() -> str:
    return _now_ist().strftime("%Y-%m-%d")

class Config:
    """Configuration management"""
    
    def __init__(self):
        # Environment
        self.ENV = os.getenv('ENV', 'development')
        self.PRODUCTION_MODE = os.getenv('PRODUCTION_MODE', '0') == '1'
        self.DEBUG = os.getenv('DEBUG', '0') == '1'
        
        # Bot
        self.BOT_TOKEN = os.getenv('BOT_TOKEN', '')
        
        # Redis
        self.REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
        
        # PostgreSQL (Optional - will use Redis only if not set)
        self.DATABASE_URL = os.getenv('DATABASE_URL', '')
        
        # Google AI
        self.GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY', '')
        self.GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')  # Fastest model
        self.GEMINI_TIMEOUT = int(os.getenv('GEMINI_TIMEOUT', '15'))  # 15 seconds max
        self.GEMINI_MAX_RETRIES = int(os.getenv('GEMINI_MAX_RETRIES', '1'))  # 1 retry for speed
        
        # MSG91 (OTP)
        self.MSG91_AUTH_KEY = os.getenv('MSG91_AUTH_KEY', '')
        self.MSG91_TEMPLATE_ID = os.getenv('MSG91_TEMPLATE_ID', '')
        
        # Quota and Pricing
        self.FREE_DAILY_QUESTIONS = int(os.getenv('FREE_DAILY_QUESTIONS', '10'))
        self.FREE_LIFETIME_QUESTIONS = int(os.getenv('FREE_LIFETIME_QUESTIONS', '30'))
        self.PRO_PRICE_INR = int(os.getenv('PRO_PRICE_INR', '49'))
        self.PRO_DURATION_DAYS = int(os.getenv('PRO_DURATION_DAYS', '30'))
        
        # Gamification
        self.XP_PER_QUESTION = int(os.getenv('XP_PER_QUESTION', '12'))
        self.XP_PER_QUIZ = int(os.getenv('XP_PER_QUIZ', '20'))
        self.XP_DAILY_CAP = int(os.getenv('XP_DAILY_CAP', '300'))
        self.STREAK_SHIELD_EVERY = int(os.getenv('STREAK_SHIELD_EVERY', '7'))
        
        # Response Cache
        self.CACHE_ENABLED = os.getenv('CACHE_ENABLED', '1') == '1'
        self.CACHE_TTL = int(os.getenv('CACHE_TTL', '3600'))  # 1 hour cache
        
        # Monitoring
        self.SENTRY_DSN = os.getenv('SENTRY_DSN', '')
        self.LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
        
        # Validate
        if self.PRODUCTION_MODE:
            if not self.BOT_TOKEN:
                raise ValueError("BOT_TOKEN is required in production")
            if not self.GOOGLE_API_KEY:
                raise ValueError("GOOGLE_API_KEY is required in production")

config = Config()

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":%(message)s}',
    datefmt="%Y-%m-%dT%H:%M:%S"
)
logger = logging.getLogger("studygenie")

# Sentry (optional)
if config.SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=config.SENTRY_DSN,
            environment=config.ENV,
            traces_sample_rate=0.1 if config.PRODUCTION_MODE else 1.0
        )
    except ImportError:
        logger.warning("Sentry SDK not installed")

# ============================================================================
# DATABASE LAYER (Redis Primary + Optional PostgreSQL)
# ============================================================================

Base = declarative_base()

class User(Base):
    """User model for PostgreSQL"""
    __tablename__ = 'bot_users'
    
    user_id = Column(Integer, primary_key=True)
    username = Column(String(100))
    full_name = Column(String(100))
    phone = Column(String(10), unique=True, index=True)
    subject = Column(String(50), default='general')
    grade = Column(String(20), default='other')
    plan = Column(String(10), default='free', index=True)
    pro_expires_at = Column(DateTime, nullable=True)
    xp = Column(Integer, default=0)
    streak = Column(Integer, default=0)
    best_streak = Column(Integer, default=0)
    shields = Column(Integer, default=0)
    last_activity = Column(String(10), default='')
    questions_asked = Column(Integer, default=0)
    quizzes_taken = Column(Integer, default=0)
    correct_answers = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    metadata = Column(JSONB, default={})

class Database:
    """Fast database manager with Redis as primary"""
    
    def __init__(self):
        self.redis = self._init_redis()
        self.engine = None
        self.Session = None
        
        if config.DATABASE_URL:
            self._init_postgres()
    
    def _init_redis(self):
        """Initialize Redis with connection pool"""
        try:
            pool = redis.ConnectionPool.from_url(
                config.REDIS_URL,
                decode_responses=True,
                max_connections=50,
                socket_timeout=3,
                socket_connect_timeout=3,
                retry_on_timeout=True
            )
            client = redis.Redis(connection_pool=pool)
            client.ping()
            logger.info("✅ Redis connected")
            return client
        except Exception as e:
            logger.warning(f"⚠️ Redis connection failed: {e}")
            return None
    
    def _init_postgres(self):
        """Initialize PostgreSQL (optional)"""
        try:
            self.engine = create_engine(
                config.DATABASE_URL,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,
                pool_recycle=3600
            )
            Base.metadata.create_all(self.engine)
            self.Session = sessionmaker(bind=self.engine)
            logger.info("✅ PostgreSQL connected")
        except Exception as e:
            logger.warning(f"⚠️ PostgreSQL connection failed: {e}")
    
    # ============ USER OPERATIONS ============
    
    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user data (fast Redis first)"""
        if self.redis:
            try:
                data = self.redis.hgetall(f"user:{user_id}")
                if data:
                    return data
            except Exception:
                pass
        
        # Fallback to PostgreSQL
        if self.Session:
            session = self.Session()
            try:
                user = session.query(User).filter_by(user_id=user_id).first()
                if user:
                    return {
                        'user_id': user.user_id,
                        'username': user.username or '',
                        'full_name': user.full_name or '',
                        'phone': user.phone or '',
                        'subject': user.subject or 'general',
                        'grade': user.grade or 'other',
                        'plan': user.plan or 'free',
                        'pro_expires_at': user.pro_expires_at.isoformat() if user.pro_expires_at else '',
                        'xp': user.xp or 0,
                        'streak': user.streak or 0,
                        'best_streak': user.best_streak or 0,
                        'shields': user.shields or 0,
                        'questions_asked': user.questions_asked or 0,
                        'quizzes_taken': user.quizzes_taken or 0,
                        'correct_answers': user.correct_answers or 0
                    }
            finally:
                session.close()
        
        return None
    
    def save_user(self, user_id: int, data: Dict[str, Any]) -> bool:
        """Save user data"""
        success = True
        
        # Save to Redis (fast)
        if self.redis:
            try:
                # Convert all values to strings for Redis
                redis_data = {k: str(v) for k, v in data.items()}
                self.redis.hset(f"user:{user_id}", mapping=redis_data)
                self.redis.expire(f"user:{user_id}", 86400 * 7)  # 7 days
            except Exception as e:
                logger.error(f"Redis save failed: {e}")
                success = False
        
        # Save to PostgreSQL (persistent)
        if self.Session:
            session = self.Session()
            try:
                user = session.query(User).filter_by(user_id=user_id).first()
                if not user:
                    user = User(user_id=user_id)
                    session.add(user)
                
                for key, value in data.items():
                    if hasattr(user, key):
                        setattr(user, key, value)
                
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"PostgreSQL save failed: {e}")
                success = False
            finally:
                session.close()
        
        return success
    
    def is_registered(self, user_id: int) -> bool:
        """Check if user is registered"""
        user = self.get_user(user_id)
        return user is not None
    
    # ============ XP & STREAK ============
    
    def add_xp(self, user_id: int, amount: int) -> int:
        """Add XP atomically"""
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
            except Exception:
                pass
        
        return new_xp
    
    def update_streak(self, user_id: int) -> Dict[str, int]:
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
        
        yesterday = (_now_ist() - timedelta(days=1)).strftime("%Y-%m-%d")
        current_streak = int(user.get('streak', 0))
        shields = int(user.get('shields', 0))
        
        if last_activity == yesterday:
            new_streak = current_streak + 1
        elif shields > 0:
            new_streak = current_streak + 1
            shields -= 1
        else:
            new_streak = 1
        
        if new_streak > 0 and new_streak % config.STREAK_SHIELD_EVERY == 0:
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
    
    # ============ QUOTA ============
    
    def check_quota(self, user_id: int) -> Tuple[bool, Dict[str, int]]:
        """Check user quota"""
        user = self.get_user(user_id)
        if not user:
            return False, {'daily_left': 0, 'lifetime_left': 0}
        
        # Pro users have unlimited
        if user.get('plan') == 'pro':
            pro_expires = user.get('pro_expires_at', '')
            if pro_expires:
                try:
                    if datetime.fromisoformat(str(pro_expires)) > datetime.utcnow():
                        return True, {'daily_left': -1, 'lifetime_left': -1}
                except:
                    pass
        
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
            except Exception:
                pass
        
        return True, {
            'daily_left': config.FREE_DAILY_QUESTIONS,
            'lifetime_left': config.FREE_LIFETIME_QUESTIONS
        }
    
    def consume_quota(self, user_id: int) -> bool:
        """Consume one question from quota"""
        if self.redis:
            try:
                today = _today_ist()
                daily_key = f"quota:daily:{user_id}:{today}"
                lifetime_key = f"quota:lifetime:{user_id}"
                
                # Atomic Lua script
                lua = """
                local daily_key = KEYS[1]
                local lifetime_key = KEYS[2]
                local daily_limit = tonumber(ARGV[1])
                local lifetime_limit = tonumber(ARGV[2])
                
                local daily_used = tonumber(redis.call('GET', daily_key) or '0')
                local lifetime_used = tonumber(redis.call('GET', lifetime_key) or '0')
                
                if daily_used >= daily_limit or lifetime_used >= lifetime_limit then
                    return 0
                end
                
                redis.call('INCR', daily_key)
                redis.call('EXPIRE', daily_key, 86400)
                redis.call('INCR', lifetime_key)
                return 1
                """
                
                script = self.redis.register_script(lua)
                return bool(script(
                    keys=[daily_key, lifetime_key],
                    args=[config.FREE_DAILY_QUESTIONS, config.FREE_LIFETIME_QUESTIONS]
                ))
            except Exception:
                pass
        
        return True
    
    # ============ LEADERBOARD ============
    
    def get_leaderboard(self, user_id: int, limit: int = 10) -> List[Dict]:
        """Get leaderboard"""
        if self.redis:
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
                
                # Add user's rank if not in top
                user_rank = self.redis.zrevrank('leaderboard', user_id)
                if user_rank is not None and user_rank >= limit:
                    user = self.get_user(user_id)
                    if user:
                        leaderboard.append({
                            'rank': user_rank + 1,
                            'user_id': user_id,
                            'name': 'You',
                            'xp': int(user.get('xp', 0))
                        })
                
                return leaderboard
            except Exception:
                pass
        
        return []

db = Database()

# ============================================================================
# AI SERVICE - OPTIMIZED FOR SPEED
# ============================================================================

class AIService:
    """Fast AI service with caching and circuit breaker"""
    
    def __init__(self):
        self.client = self._init_client()
        self.cache = {}  # In-memory response cache
        self.circuit_breaker = {'failures': 0, 'open_until': 0}
    
    def _init_client(self):
        """Initialize Gemini client"""
        if not config.GOOGLE_API_KEY:
            logger.error("❌ Google API key not set")
            return None
        
        try:
            client = genai.Client(
                api_key=config.GOOGLE_API_KEY,
                http_options=genai_types.HttpOptions(
                    timeout=config.GEMINI_TIMEOUT * 1000
                )
            )
            logger.info(f"✅ Gemini initialized: {config.GEMINI_MODEL}")
            return client
        except Exception as e:
            logger.error(f"❌ Failed to init Gemini: {e}")
            return None
    
    def answer_question(self, question: str, tool: str = 'general', context: str = '') -> Optional[str]:
        """Generate answer with caching and retries"""
        if not self.client:
            return "AI service is currently unavailable. Please try again later."
        
        # Check circuit breaker
        if time.time() < self.circuit_breaker['open_until']:
            return "Service temporarily unavailable. Please try again in a minute."
        
        # Check cache first (instant response for repeated questions)
        cache_key = f"{tool}:{question.lower().strip()}"
        if config.CACHE_ENABLED and cache_key in self.cache:
            logger.info(f"⚡ Cache hit: {question[:50]}...")
            return self.cache[cache_key]
        
        # Build prompt
        prompt = self._build_prompt(question, tool, context)
        
        # Generate with retries
        for attempt in range(config.GEMINI_MAX_RETRIES + 1):
            try:
                start_time = time.time()
                response = self.client.models.generate_content(
                    model=config.GEMINI_MODEL,
                    contents=[prompt],
                    config=genai_types.GenerateContentConfig(
                        temperature=0.7,
                        max_output_tokens=2048,  # Limit for speed
                    )
                )
                
                duration = time.time() - start_time
                logger.info(f"⚡ Generated in {duration:.2f}s: {question[:50]}...")
                
                answer = response.text
                
                # Cache the response
                if config.CACHE_ENABLED:
                    self.cache[cache_key] = answer
                    # Limit cache size
                    if len(self.cache) > 1000:
                        # Remove oldest entries
                        for key in list(self.cache.keys())[:100]:
                            del self.cache[key]
                
                self.circuit_breaker['failures'] = 0
                return answer
                
            except Exception as e:
                logger.warning(f"⚠️ Gemini attempt {attempt + 1} failed: {e}")
                if attempt < config.GEMINI_MAX_RETRIES:
                    time.sleep(0.5)  # Short delay for retry
        
        # Circuit breaker
        self.circuit_breaker['failures'] += 1
        if self.circuit_breaker['failures'] >= 5:
            self.circuit_breaker['open_until'] = time.time() + 60
            logger.error("🔴 Circuit breaker opened")
        
        return None
    
    def generate_quiz(self, topic: str, num: int = 5) -> Optional[List[Dict]]:
        """Generate quiz questions fast"""
        prompt = f"""Generate {num} MCQs about {topic}. Format:
Q: question
A) option1
B) option2
C) option3
D) option4
Correct: A/B/C/D
Explanation: brief

Separate with ---"""
        
        response = self.answer_question(prompt, 'quiz')
        if not response:
            return None
        
        # Parse quiz
        questions = []
        for block in response.split('---'):
            block = block.strip()
            if not block:
                continue
            
            q_data = {'options': {}}
            for line in block.split('\n'):
                line = line.strip()
                if line.startswith('Q:'):
                    q_data['question'] = line[2:].strip()
                elif line.startswith('A)'):
                    q_data['options']['A'] = line[2:].strip()
                elif line.startswith('B)'):
                    q_data['options']['B'] = line[2:].strip()
                elif line.startswith('C)'):
                    q_data['options']['C'] = line[2:].strip()
                elif line.startswith('D)'):
                    q_data['options']['D'] = line[2:].strip()
                elif line.startswith('Correct:'):
                    q_data['correct'] = line[8:].strip().upper()
                elif line.startswith('Explanation:'):
                    q_data['explanation'] = line[12:].strip()
            
            if 'question' in q_data and len(q_data['options']) == 4:
                questions.append(q_data)
        
        return questions
    
    def _build_prompt(self, question: str, tool: str, context: str) -> str:
        """Build optimized prompt"""
        base = (
            "You are StudyGenie, an expert AI tutor for Indian students (JEE, NEET, GATE, Boards). "
            "Answer in Hinglish (Hindi + English mix). Be encouraging, use emojis, explain step-by-step.\n\n"
        )
        
        tool_prompts = {
            'general': f"{base}Question: {question}",
            'explain': f"{base}Explain simply with examples.\n\nConcept: {question}",
            'solve': f"{base}Solve step-by-step showing all work.\n\nProblem: {question}",
            'notes': f"{base}Create concise revision notes.\n\nTopic: {question}",
            'pyq': f"{base}Solve this PYQ with exam tips.\n\nQuestion: {question}",
            'formula': f"{base}List important formulas.\n\nTopic: {question}",
            'quiz': question,  # Already formatted
        }
        
        prompt = tool_prompts.get(tool, tool_prompts['general'])
        if context and tool != 'quiz':
            prompt += f"\n\nContext: {context}"
        
        return prompt

ai_service = AIService()

# ============================================================================
# KEYBOARDS
# ============================================================================

class Keyboards:
    """Keyboard builders"""
    
    @staticmethod
    def main_menu(user_data=None) -> InlineKeyboardMarkup:
        """Main menu"""
        keyboard = [
            [InlineKeyboardButton("📚 Ask Question", callback_data="menu_ask"),
             InlineKeyboardButton("🎯 Quiz", callback_data="menu_quiz")],
            [InlineKeyboardButton("📖 Study Tools", callback_data="menu_tools"),
             InlineKeyboardButton("📊 Progress", callback_data="menu_progress")],
            [InlineKeyboardButton("🏆 Leaderboard", callback_data="menu_leaderboard"),
             InlineKeyboardButton("🔥 Streak", callback_data="menu_streak")],
            [InlineKeyboardButton("💎 Upgrade to Pro", callback_data="menu_upgrade")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def tools_menu() -> InlineKeyboardMarkup:
        """Tools menu"""
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
        """Quiz answer options"""
        keyboard = [
            [InlineKeyboardButton("A", callback_data="quiz_A"),
             InlineKeyboardButton("B", callback_data="quiz_B")],
            [InlineKeyboardButton("C", callback_data="quiz_C"),
             InlineKeyboardButton("D", callback_data="quiz_D")],
            [InlineKeyboardButton("❌ Stop Quiz", callback_data="quiz_stop")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def registration_skip() -> InlineKeyboardMarkup:
        """Skip registration"""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭️ Skip (Quick Start)", callback_data="skip_registration")]
        ])

keyboards = Keyboards()

# ============================================================================
# CONVERSATION STATES
# ============================================================================

(PHONE_INPUT, OTP_INPUT, NAME_INPUT) = range(3)

# ============================================================================
# MAIN BOT CLASS
# ============================================================================

class StudyGenieBot:
    """Main bot class - optimized for speed"""
    
    def __init__(self):
        self.app = None
        self.active_quizzes = {}
        self.user_tools = {}  # Store user's selected tool
    
    async def setup(self):
        """Setup bot"""
        defaults = Defaults(
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
        
        self.app = ApplicationBuilder()\
            .token(config.BOT_TOKEN)\
            .defaults(defaults)\
            .connect_timeout(10)\
            .read_timeout(20)\
            .write_timeout(20)\
            .build()
        
        self._register_handlers()
        await self._set_commands()
        
        logger.info("✅ Bot setup completed")
        return self.app
    
    def _register_handlers(self):
        """Register all handlers"""
        
        # Registration (simplified)
        reg_conv = ConversationHandler(
            entry_points=[CommandHandler("start", self.start)],
            states={
                NAME_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_name)],
                PHONE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_phone)],
                OTP_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_otp)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)],
            allow_reentry=True
        )
        self.app.add_handler(reg_conv)
        
        # Main commands
        self.app.add_handler(CommandHandler("menu", self.show_menu))
        self.app.add_handler(CommandHandler("ask", self.ask_question))
        self.app.add_handler(CommandHandler("explain", self.explain_topic))
        self.app.add_handler(CommandHandler("solve", self.solve_problem))
        self.app.add_handler(CommandHandler("notes", self.create_notes))
        self.app.add_handler(CommandHandler("pyq", self.pyq_solver))
        self.app.add_handler(CommandHandler("formula", self.formula_list))
        self.app.add_handler(CommandHandler("quiz", self.start_quiz))
        self.app.add_handler(CommandHandler("progress", self.show_progress))
        self.app.add_handler(CommandHandler("streak", self.show_streak))
        self.app.add_handler(CommandHandler("leaderboard", self.show_leaderboard))
        self.app.add_handler(CommandHandler("upgrade", self.upgrade))
        
        # Callback handler
        self.app.add_handler(CallbackQueryHandler(self.handle_callback))
        
        # Free text handler (auto-detect)
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self.handle_free_text
        ))
        
        # Error handler
        self.app.add_error_handler(self.error_handler)
    
    async def _set_commands(self):
        """Set bot commands"""
        commands = [
            BotCommand("start", "🚀 Start/Register"),
            BotCommand("menu", "📋 Main Menu"),
            BotCommand("ask", "❓ Ask Question"),
            BotCommand("quiz", "🎯 Take Quiz"),
            BotCommand("progress", "📊 Progress"),
            BotCommand("streak", "🔥 Streak"),
            BotCommand("leaderboard", "🏆 Leaderboard"),
            BotCommand("upgrade", "💎 Go Pro")
        ]
        await self.app.bot.set_my_commands(commands)
    
    # ============ REGISTRATION ============
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command - quick registration"""
        user_id = update.effective_user.id
        
        # Check if already registered
        if db.is_registered(user_id):
            await self.show_menu(update, context)
            return ConversationHandler.END
        
        # Quick registration
        await update.message.reply_text(
            "🎓 *Welcome to StudyGenie!*\n\n"
            "Your AI tutor for JEE, NEET, GATE & Boards.\n\n"
            "Let's get you started!\n"
            "What's your name? (max 18 chars)\n\n"
            "*OR* send /menu to skip registration and start using immediately!"
        )
        return NAME_INPUT
    
    async def handle_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle name input"""
        name = update.message.text.strip()[:18]
        
        if len(name) < 2:
            await update.message.reply_text("Name too short. Please enter at least 2 characters:")
            return NAME_INPUT
        
        user_id = update.effective_user.id
        user_data = {
            'user_id': user_id,
            'username': update.effective_user.username or '',
            'full_name': name,
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
            f"✅ *Welcome, {name}!*\n\n"
            f"You're all set to start learning!\n\n"
            f"🎁 You have:\n"
            f"• {config.FREE_DAILY_QUESTIONS} free questions daily\n"
            f"• {config.FREE_LIFETIME_QUESTIONS} free lifetime questions\n\n"
            f"Use /menu to see all options!"
        )
        
        # Show menu
        await self.show_menu(update, context)
        return ConversationHandler.END
    
    async def handle_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle phone (optional)"""
        # Simplified - phone is optional
        return await self.handle_name(update, context)
    
    async def handle_otp(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle OTP (optional)"""
        # Simplified - OTP is optional
        return await self.handle_name(update, context)
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel registration"""
        await update.message.reply_text(
            "Registration cancelled. Use /menu to skip registration and start using!"
        )
        return ConversationHandler.END
    
    # ============ MAIN MENU ============
    
    async def show_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show main menu"""
        user_id = update.effective_user.id
        user = db.get_user(user_id)
        
        if not user:
            # Auto-register with Telegram name
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
        
        # Update streak
        streak_data = db.update_streak(user_id)
        user = db.get_user(user_id) or user_data
        
        is_pro = user.get('plan') == 'pro'
        quota = db.check_quota(user_id)
        
        message = (
            f"🎓 *StudyGenie*\n\n"
            f"👤 {user.get('full_name', 'Student')}\n"
            f"⭐ XP: {user.get('xp', 0)}\n"
            f"🔥 Streak: {streak_data['current']} days\n"
        )
        
        if is_pro:
            message += "\n💎 *PRO Member* - Unlimited\n"
        else:
            daily_left = quota[1].get('daily_left', 0)
            message += f"\n❓ Questions left today: {daily_left}\n"
        
        message += "\n*Choose an option:*"
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                message,
                reply_markup=keyboards.main_menu(user)
            )
        else:
            await update.message.reply_text(
                message,
                reply_markup=keyboards.main_menu(user)
            )
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all callbacks"""
        query = update.callback_query
        data = query.data
        await query.answer()
        
        if data == "menu_main":
            await self.show_menu(update, context)
        
        elif data == "menu_ask":
            await query.edit_message_text(
                "📚 *Ask a Question*\n\n"
                "Simply type your question directly!\n\n"
                "Examples:\n"
                "• What is Newton's second law?\n"
                "• Solve: 2x + 5 = 15\n"
                "• Explain photosynthesis\n\n"
                "Or use /ask <question>"
            )
        
        elif data == "menu_quiz":
            await self.start_quiz_command(update, context)
        
        elif data == "menu_tools":
            await query.edit_message_text(
                "📖 *Study Tools*\n\n"
                "Select a tool:",
                reply_markup=keyboards.tools_menu()
            )
        
        elif data == "menu_progress":
            await self.show_progress_command(update, context)
        
        elif data == "menu_leaderboard":
            await self.show_leaderboard_command(update, context)
        
        elif data == "menu_streak":
            await self.show_streak_command(update, context)
        
        elif data == "menu_upgrade":
            await self.upgrade_command(update, context)
        
        elif data.startswith("tool_"):
            tool = data.replace("tool_", "")
            self.user_tools[update.effective_user.id] = tool
            await query.edit_message_text(
                f"✅ *{tool.title()} tool selected*\n\n"
                f"Type your question directly!\n\n"
                f"Example for {tool}:\n"
                f"• {self._get_tool_example(tool)}"
            )
        
        elif data.startswith("quiz_"):
            await self.handle_quiz_answer(update, context)
    
    def _get_tool_example(self, tool: str) -> str:
        """Get example for tool"""
        examples = {
            'explain': "Explain quantum mechanics simply",
            'solve': "Solve: x² + 5x + 6 = 0",
            'notes': "Notes on thermodynamics",
            'pyq': "JEE 2023 question on kinematics",
            'formula': "All formulas of electrostatics"
        }
        return examples.get(tool, "Type your question here")
    
    # ============ QUESTION HANDLING ============
    
    async def ask_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Ask question command"""
        question = ' '.join(context.args) if context.args else ''
        
        if not question:
            await update.message.reply_text(
                "📚 *Ask a Question*\n\n"
                "Usage: /ask <your question>\n\n"
                "Example: /ask What is Newton's second law?\n\n"
                "Or just type your question directly!"
            )
            return
        
        await self.process_question(update, context, question, 'general')
    
    async def explain_topic(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        topic = ' '.join(context.args) if context.args else ''
        if topic:
            await self.process_question(update, context, topic, 'explain')
        else:
            await update.message.reply_text("Please provide a topic: /explain <topic>")
    
    async def solve_problem(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        problem = ' '.join(context.args) if context.args else ''
        if problem:
            await self.process_question(update, context, problem, 'solve')
        else:
            await update.message.reply_text("Please provide a problem: /solve <problem>")
    
    async def create_notes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        topic = ' '.join(context.args) if context.args else ''
        if topic:
            await self.process_question(update, context, topic, 'notes')
        else:
            await update.message.reply_text("Please provide a topic: /notes <topic>")
    
    async def pyq_solver(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        question = ' '.join(context.args) if context.args else ''
        if question:
            await self.process_question(update, context, question, 'pyq')
        else:
            await update.message.reply_text("Please provide a PYQ: /pyq <question>")
    
    async def formula_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        topic = ' '.join(context.args) if context.args else ''
        if topic:
            await self.process_question(update, context, topic, 'formula')
        else:
            await update.message.reply_text("Please provide a topic: /formula <topic>")
    
    async def handle_free_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle free text - auto-detect intent"""
        text = update.message.text.strip()
        
        # Check if user has selected a tool
        user_id = update.effective_user.id
        tool = self.user_tools.get(user_id, 'general')
        
        # Auto-detect intent if no tool selected
        if tool == 'general':
            lower = text.lower()
            if lower.startswith(('explain', 'what is', 'why', 'how')):
                tool = 'explain'
            elif lower.startswith(('solve', 'calculate', 'find')):
                tool = 'solve'
            elif lower.startswith(('notes', 'summarize')):
                tool = 'notes'
        
        await self.process_question(update, context, text, tool)
    
    async def process_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                              question: str, tool: str = 'general'):
        """Process question - OPTIMIZED FOR SPEED"""
        user_id = update.effective_user.id
        user = db.get_user(user_id)
        
        if not user:
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
            user = user_data
        
        # Check quota (Pro users skip)
        if user.get('plan') != 'pro':
            can_ask, quota = db.check_quota(user_id)
            if not can_ask:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 Upgrade to Pro", callback_data="menu_upgrade")]
                ])
                await update.message.reply_text(
                    "❌ *Daily quota exceeded!*\n\n"
                    f"You've used all {config.FREE_DAILY_QUESTIONS} free questions today.\n\n"
                    "Upgrade to Pro for unlimited access!",
                    reply_markup=keyboard
                )
                return
        
        # Show typing indicator
        await update.message.chat.send_action(ChatAction.TYPING)
        
        # Generate answer (with speed logging)
        start_time = time.time()
        answer = ai_service.answer_question(question, tool)
        response_time = time.time() - start_time
        
        if not answer:
            await update.message.reply_text(
                "😔 Sorry, I'm having trouble processing this. Please try again."
            )
            return
        
        # Consume quota and award XP
        if user.get('plan') != 'pro':
            db.consume_quota(user_id)
        
        xp_awarded = config.XP_PER_QUESTION
        db.add_xp(user_id, xp_awarded)
        
        # Update stats
        user['questions_asked'] = int(user.get('questions_asked', 0)) + 1
        db.save_user(user_id, user)
        
        # Send answer with XP
        message = (
            f"{answer}\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⚡ {response_time:.1f}s | ⭐ +{xp_awarded} XP"
        )
        
        # Split long messages
        if len(message) > 4096:
            parts = [message[i:i+4000] for i in range(0, len(message), 4000)]
            for part in parts:
                await update.message.reply_text(part)
        else:
            await update.message.reply_text(message)
    
    # ============ QUIZ ============
    
    async def start_quiz(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start quiz"""
        topic = ' '.join(context.args) if context.args else ''
        await self.start_quiz_command(update, context, topic)
    
    async def start_quiz_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE, topic: str = ''):
        """Start quiz command"""
        user_id = update.effective_user.id
        user = db.get_user(user_id)
        
        if not topic:
            topic = user.get('subject', 'general') if user else 'general'
        
        # Show typing
        if update.effective_message:
            await update.effective_message.chat.send_action(ChatAction.TYPING)
        
        # Generate quiz
        questions = ai_service.generate_quiz(topic, 5)
        
        if not questions:
            await update.effective_message.reply_text(
                "😔 Failed to generate quiz. Please try again."
            )
            return
        
        # Store quiz session
        self.active_quizzes[user_id] = {
            'questions': questions,
            'current': 0,
            'score': 0,
            'answers': []
        }
        
        # Send first question
        await self.send_quiz_question(update, context, user_id)
    
    async def send_quiz_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
        """Send quiz question"""
        quiz = self.active_quizzes.get(user_id)
        if not quiz:
            return
        
        questions = quiz['questions']
        current = quiz['current']
        
        if current >= len(questions):
            await self.finish_quiz(update, context, user_id)
            return
        
        question = questions[current]
        options = question.get('options', {})
        
        message = (
            f"🎯 *Question {current + 1} of {len(questions)}*\n\n"
            f"{question['question']}\n\n"
            f"A) {options.get('A', '')}\n"
            f"B) {options.get('B', '')}\n"
            f"C) {options.get('C', '')}\n"
            f"D) {options.get('D', '')}"
        )
        
        if update.effective_message:
            await update.effective_message.reply_text(
                message,
                reply_markup=keyboards.quiz_options()
            )
        elif update.callback_query:
            await update.callback_query.message.reply_text(
                message,
                reply_markup=keyboards.quiz_options()
            )
    
    async def handle_quiz_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle quiz answer"""
        query = update.callback_query
        data = query.data
        await query.answer()
        
        user_id = update.effective_user.id
        quiz = self.active_quizzes.get(user_id)
        
        if not quiz:
            await query.edit_message_text("Quiz session expired. Start a new quiz with /quiz")
            return
        
        if data == "quiz_stop":
            await self.finish_quiz(update, context, user_id)
            return
        
        answer = data.replace('quiz_', '')
        questions = quiz['questions']
        current = quiz['current']
        question = questions[current]
        correct = question.get('correct', '').upper()
        
        is_correct = answer == correct
        if is_correct:
            quiz['score'] += 1
        
        # Show result
        if is_correct:
            await query.edit_message_text(
                f"✅ *Correct!*\n\n"
                f"{question.get('explanation', '')}\n\n"
                f"Score: {quiz['score']}/{current + 1}"
            )
        else:
            await query.edit_message_text(
                f"❌ *Wrong!*\n\n"
                f"Correct: {correct}\n"
                f"{question.get('explanation', '')}\n\n"
                f"Score: {quiz['score']}/{current + 1}"
            )
        
        # Next question
        quiz['current'] += 1
        await asyncio.sleep(1.5)
        await self.send_quiz_question(update, context, user_id)
    
    async def finish_quiz(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
        """Finish quiz"""
        quiz = self.active_quizzes.pop(user_id, None)
        if not quiz:
            return
        
        total = len(quiz['questions'])
        score = quiz['score']
        percentage = (score / total * 100) if total > 0 else 0
        
        # Award XP
        xp_awarded = config.XP_PER_QUIZ + (score * 5)
        db.add_xp(user_id, xp_awarded)
        
        # Feedback
        if percentage >= 80:
            feedback = "🌟 Excellent!"
        elif percentage >= 60:
            feedback = "👍 Good job!"
        elif percentage >= 40:
            feedback = "📚 Keep practicing!"
        else:
            feedback = "💪 Don't give up!"
        
        message = (
            f"🎯 *Quiz Complete!*\n\n"
            f"Score: {score}/{total} ({percentage:.0f}%)\n"
            f"XP Earned: +{xp_awarded}\n\n"
            f"{feedback}"
        )
        
        if update.effective_message:
            await update.effective_message.reply_text(message)
        elif update.callback_query:
            await update.callback_query.message.reply_text(message)
    
    # ============ PROGRESS & STATS ============
    
    async def show_progress(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.show_progress_command(update, context)
    
    async def show_progress_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show progress"""
        user_id = update.effective_user.id
        user = db.get_user(user_id)
        
        if not user:
            await self.show_menu(update, context)
            return
        
        xp = int(user.get('xp', 0))
        level = (xp // 100) + 1
        xp_in_level = xp % 100
        
        # Progress bar
        bar_length = 10
        filled = int(xp_in_level / 100 * bar_length)
        bar = "█" * filled + "░" * (bar_length - filled)
        
        message = (
            f"📊 *Progress*\n\n"
            f"⭐ Level: {level}\n"
            f"📈 XP: {xp}\n"
            f"{bar} {xp_in_level}/100\n\n"
            f"🔥 Streak: {user.get('streak', 0)} days\n"
            f"🛡️ Shields: {user.get('shields', 0)}\n"
            f"📚 Questions: {user.get('questions_asked', 0)}\n"
            f"🎯 Quizzes: {user.get('quizzes_taken', 0)}\n"
        )
        
        if update.callback_query:
            await update.callback_query.edit_message_text(message)
        else:
            await update.message.reply_text(message)
    
    async def show_streak(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.show_streak_command(update, context)
    
    async def show_streak_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show streak"""
        user_id = update.effective_user.id
        user = db.get_user(user_id)
        
        if not user:
            await self.show_menu(update, context)
            return
        
        streak = int(user.get('streak', 0))
        best = int(user.get('best_streak', 0))
        shields = int(user.get('shields', 0))
        
        message = (
            f"🔥 *Streak*\n\n"
            f"Current: {streak} days\n"
            f"Best: {best} days\n"
            f"Shields: {shields}\n\n"
            f"{'Keep it up! 💪' if streak > 0 else 'Start studying today!'}"
        )
        
        if update.callback_query:
            await update.callback_query.edit_message_text(message)
        else:
            await update.message.reply_text(message)
    
    async def show_leaderboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.show_leaderboard_command(update, context)
    
    async def show_leaderboard_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show leaderboard"""
        user_id = update.effective_user.id
        leaderboard = db.get_leaderboard(user_id)
        
        if not leaderboard:
            message = "🏆 *Leaderboard*\n\nNo data yet. Be the first!"
        else:
            message = "🏆 *Top Students*\n\n"
            for entry in leaderboard[:10]:
                medal = "🥇" if entry['rank'] == 1 else "🥈" if entry['rank'] == 2 else "🥉" if entry['rank'] == 3 else f"{entry['rank']}."
                message += f"{medal} {entry['name']}: {entry['xp']} XP\n"
        
        if update.callback_query:
            await update.callback_query.edit_message_text(message)
        else:
            await update.message.reply_text(message)
    
    async def upgrade(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.upgrade_command(update, context)
    
    async def upgrade_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Upgrade to Pro"""
        user_id = update.effective_user.id
        user = db.get_user(user_id)
        
        if not user:
            await self.show_menu(update, context)
            return
        
        if user.get('plan') == 'pro':
            message = "✅ You're already a Pro member!"
        else:
            message = (
                f"💎 *Upgrade to Pro*\n\n"
                f"• Unlimited questions\n"
                f"• All study tools\n"
                f"• Priority responses\n\n"
                f"Price: ₹{config.PRO_PRICE_INR}/month\n\n"
                f"To upgrade:\n"
                f"1. Pay ₹{config.PRO_PRICE_INR} to UPI: studygenie@upi\n"
                f"2. Send payment screenshot to admin\n\n"
                f"Your account will be upgraded within minutes!"
            )
        
        if update.callback_query:
            await update.callback_query.edit_message_text(message)
        else:
            await update.message.reply_text(message)
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors"""
        logger.error(f"Update {update} caused error {context.error}")
        
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "😔 Something went wrong. Please try again."
            )
    
    def run(self):
        """Run the bot"""
        logger.info(f"🚀 Starting StudyGenie Bot in {config.ENV} mode")
        
        import asyncio
        asyncio.run(self.setup())
        self.app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    if not config.BOT_TOKEN:
        logger.error("❌ BOT_TOKEN is not set. Please set it in .env file.")
        exit(1)
    
    bot = StudyGenieBot()
    bot.run()
