"""
StudyGenie by Sparsh Singhal
Fully Gamified Multi-Platform E-Learning Bot
Telegram + WhatsApp + Web Dashboard
Production-ready for Vercel / any Python host
Author & Creator: Sparsh Singhal
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import redis
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request, render_template_string, send_from_directory
from google import genai
from google.genai import types as genai_types
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    Defaults,
    MessageHandler,
    filters,
)

load_dotenv()

# ============================================================================
# CONFIG
# ============================================================================

IST = ZoneInfo("Asia/Kolkata")


def _now_ist() -> datetime:
    return datetime.now(IST)


def _today_ist() -> str:
    return _now_ist().strftime("%Y-%m-%d")


class Config:
    def __init__(self) -> None:
        # Telegram
        self.BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
        self.VERCEL_URL = os.getenv("VERCEL_URL", "").strip()
        self.WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()

        # Redis
        self.REDIS_URL = (os.getenv("REDIS_URL") or os.getenv("UPSTASH_REDIS_URL") or "").strip()

        # Gemini
        self.GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()
        self.GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        # Quotas
        self.FREE_DAILY = int(os.getenv("FREE_DAILY_QUESTIONS", "8"))
        self.FREE_LIFETIME = int(os.getenv("FREE_LIFETIME_QUESTIONS", "25"))

        # Razorpay
        self.PRO_PRICE_INR = int(os.getenv("PRO_PRICE_INR", "49"))
        self.RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "").strip()
        self.RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
        self.RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "").strip()

        # WhatsApp (Meta Cloud API)
        self.WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "").strip()
        self.WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
        self.WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "studygenie_sparsh").strip()
        self.WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v20.0")

        # Gamification
        self.XP_QUESTION = 15
        self.XP_QUIZ = 25
        self.XP_DAILY_QUEST = 40
        self.XP_REFERRAL = 100
        self.CACHE_TTL = 3600

        self.validate()

    def validate(self) -> None:
        if not self.BOT_TOKEN:
            raise ValueError("BOT_TOKEN required")
        if not self.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY required")


config = Config()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("studygenie")

# ============================================================================
# DATABASE (supports both Telegram numeric ID and WhatsApp phone)
# ============================================================================


class Database:
    def __init__(self) -> None:
        self.redis = self._connect()

    def _connect(self) -> Optional[redis.Redis]:
        if not config.REDIS_URL:
            logger.warning("No Redis – limited mode")
            return None
        try:
            r = redis.from_url(
                config.REDIS_URL,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
                retry_on_timeout=True,
            )
            r.ping()
            logger.info("Redis OK")
            return r
        except Exception as e:
            logger.error("Redis fail: %s", e)
            return None

    def _key(self, uid: str | int) -> str:
        return f"user:{uid}"

    def get_user(self, uid: str | int) -> Optional[Dict[str, str]]:
        if not self.redis:
            return None
        try:
            data = self.redis.hgetall(self._key(uid))
            return data or None
        except Exception:
            return None

    def save_user(self, uid: str | int, data: Dict[str, Any]) -> bool:
        if not self.redis:
            return False
        try:
            payload = {k: str(v) for k, v in data.items()}
            pipe = self.redis.pipeline()
            pipe.hset(self._key(uid), mapping=payload)
            pipe.expire(self._key(uid), 86400 * 120)
            pipe.execute()
            return True
        except Exception as e:
            logger.error("save_user: %s", e)
            return False

    def ensure_user(self, uid: str | int, username: str = "", full_name: str = "", platform: str = "telegram") -> Dict[str, str]:
        user = self.get_user(uid)
        if user:
            return user
        data = {
            "user_id": str(uid),
            "username": username or "",
            "full_name": full_name or "Student",
            "platform": platform,
            "plan": "free",
            "pro_until": "",
            "xp": "0",
            "level": "1",
            "streak": "0",
            "best_streak": "0",
            "shields": "0",
            "questions_asked": "0",
            "quizzes_taken": "0",
            "correct_answers": "0",
            "badges": "[]",
            "daily_quest": "",
            "quest_progress": "0",
            "referral_code": secrets.token_hex(4).upper(),
            "referred_by": "",
            "last_activity": _today_ist(),
            "created_at": _today_ist(),
        }
        self.save_user(uid, data)
        return data

    def is_pro(self, uid: str | int) -> bool:
        user = self.get_user(uid)
        if not user:
            return False
        if user.get("plan") != "pro":
            return False
        until = user.get("pro_until", "")
        if not until:
            return True
        try:
            return datetime.fromisoformat(until) > _now_ist()
        except Exception:
            return False

    def activate_pro(self, uid: str | int, days: int = 30) -> bool:
        user = self.get_user(uid) or self.ensure_user(uid)
        until = (_now_ist() + timedelta(days=days)).isoformat()
        user["plan"] = "pro"
        user["pro_until"] = until
        return self.save_user(uid, user)

    def add_xp(self, uid: str | int, amount: int) -> Tuple[int, int]:
        user = self.get_user(uid)
        if not user:
            return 0, 1
        xp = int(user.get("xp", 0)) + amount
        level = (xp // 100) + 1
        user["xp"] = str(xp)
        user["level"] = str(level)
        self.save_user(uid, user)
        if self.redis:
            try:
                self.redis.zadd("leaderboard", {str(uid): xp})
            except Exception:
                pass
        return xp, level

    def update_streak(self, uid: str | int) -> Dict[str, int]:
        user = self.get_user(uid)
        if not user:
            return {"current": 0, "best": 0, "shields": 0}
        today = _today_ist()
        last = user.get("last_activity", "")
        if last == today:
            return {
                "current": int(user.get("streak", 0)),
                "best": int(user.get("best_streak", 0)),
                "shields": int(user.get("shields", 0)),
            }
        yesterday = (_now_ist() - timedelta(days=1)).strftime("%Y-%m-%d")
        current = int(user.get("streak", 0))
        shields = int(user.get("shields", 0))
        if last == yesterday:
            new = current + 1
        elif shields > 0:
            new = current + 1
            shields -= 1
        else:
            new = 1
        if new > 0 and new % 7 == 0:
            shields += 1
        best = max(new, int(user.get("best_streak", 0)))
        user.update({
            "streak": str(new),
            "best_streak": str(best),
            "shields": str(shields),
            "last_activity": today,
        })
        self.save_user(uid, user)
        return {"current": new, "best": best, "shields": shields}

    def check_quota(self, uid: str | int) -> Tuple[bool, Dict[str, int]]:
        if self.is_pro(uid):
            return True, {"daily_left": -1, "lifetime_left": -1}
        if not self.redis:
            return True, {"daily_left": config.FREE_DAILY, "lifetime_left": config.FREE_LIFETIME}
        try:
            today = _today_ist()
            dkey = f"quota:daily:{uid}:{today}"
            lkey = f"quota:lifetime:{uid}"
            daily_used = int(self.redis.get(dkey) or 0)
            life_used = int(self.redis.get(lkey) or 0)
            daily_left = max(0, config.FREE_DAILY - daily_used)
            life_left = max(0, config.FREE_LIFETIME - life_used)
            return (daily_left > 0 and life_left > 0), {
                "daily_left": daily_left,
                "lifetime_left": life_left,
            }
        except Exception:
            return True, {"daily_left": config.FREE_DAILY, "lifetime_left": config.FREE_LIFETIME}

    def consume_quota(self, uid: str | int) -> None:
        if self.is_pro(uid) or not self.redis:
            return
        try:
            today = _today_ist()
            pipe = self.redis.pipeline()
            pipe.incr(f"quota:daily:{uid}:{today}")
            pipe.expire(f"quota:daily:{uid}:{today}", 90000)
            pipe.incr(f"quota:lifetime:{uid}")
            pipe.execute()
        except Exception:
            pass

    def get_leaderboard(self, limit: int = 10) -> List[Dict]:
        if not self.redis:
            return []
        try:
            top = self.redis.zrevrange("leaderboard", 0, limit - 1, withscores=True)
            out = []
            for rank, (uid, xp) in enumerate(top, 1):
                u = self.get_user(uid)
                out.append({
                    "rank": rank,
                    "name": (u or {}).get("full_name", "Student"),
                    "xp": int(xp),
                    "level": int((u or {}).get("level", 1)),
                })
            return out
        except Exception:
            return []

    def get_rank(self, uid: str | int) -> Optional[int]:
        if not self.redis:
            return None
        try:
            r = self.redis.zrevrank("leaderboard", str(uid))
            return r + 1 if r is not None else None
        except Exception:
            return None

    def add_badge(self, uid: str | int, badge: str) -> None:
        user = self.get_user(uid)
        if not user:
            return
        try:
            badges = json.loads(user.get("badges", "[]"))
        except Exception:
            badges = []
        if badge not in badges:
            badges.append(badge)
            user["badges"] = json.dumps(badges)
            self.save_user(uid, user)

    def set_daily_quest(self, uid: str | int) -> str:
        quests = [
            "Ask 3 questions today",
            "Complete 1 quiz",
            "Use Solve tool twice",
            "Maintain streak",
            "Explain any concept",
        ]
        quest = secrets.choice(quests)
        user = self.get_user(uid) or {}
        user["daily_quest"] = quest
        user["quest_progress"] = "0"
        self.save_user(uid, user)
        return quest


db = Database()

# ============================================================================
# AI SERVICE
# ============================================================================


class AIService:
    def __init__(self) -> None:
        self.client = None
        if config.GOOGLE_API_KEY:
            try:
                self.client = genai.Client(api_key=config.GOOGLE_API_KEY)
            except Exception as e:
                logger.error("Gemini init: %s", e)

    def answer(self, question: str, tool: str = "general", is_pro: bool = False) -> Optional[str]:
        if not self.client:
            return "AI temporarily unavailable. Try again soon."

        cache_key = f"ai:{tool}:{hashlib.md5(question.lower().encode()).hexdigest()}"
        if db.redis:
            try:
                cached = db.redis.get(cache_key)
                if cached:
                    return cached
            except Exception:
                pass

        base = (
            "You are StudyGenie by Sparsh Singhal – India's most fun gamified AI tutor "
            "for JEE/NEET/GATE/Boards. Created with ❤️ by Sparsh Singhal. "
            "Reply in natural Hinglish. Be encouraging, use emojis, explain step-by-step. "
            "Keep answers clear and exam-oriented.\n\n"
        )
        if is_pro:
            base += "User is PRO – give deeper explanations, extra tips, memory tricks and exam strategy.\n\n"

        templates = {
            "general": f"{base}Question:\n{question}",
            "explain": f"{base}Explain simply with examples + analogy.\n\n{question}",
            "solve": f"{base}Solve step-by-step with full working.\n\n{question}",
            "notes": f"{base}Create short exam-ready notes + key formulas.\n\n{question}",
            "pyq": f"{base}Solve this PYQ carefully.\n\n{question}",
            "formula": f"{base}List all important formulas with short notes.\n\n{question}",
            "planner": f"{base}Create a realistic 7-day study plan.\n\nTopic/Goal: {question}",
            "mock": f"{base}Generate 5 high-quality MCQs with answers + explanations.\n\nTopic: {question}",
        }
        prompt = templates.get(tool, templates["general"])

        try:
            resp = self.client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=[prompt],
                config=genai_types.GenerateContentConfig(
                    temperature=0.35,
                    max_output_tokens=2500 if is_pro else 1800,
                ),
            )
            text = (resp.text or "").strip()
            if text and db.redis:
                try:
                    db.redis.setex(cache_key, config.CACHE_TTL, text)
                except Exception:
                    pass
            return text or None
        except Exception as e:
            logger.error("Gemini: %s", e)
            return None


ai = AIService()

# ============================================================================
# WHATSAPP HELPER
# ============================================================================


def send_whatsapp_message(to: str, text: str) -> bool:
    """Send a text message via Meta Cloud API."""
    if not config.WHATSAPP_TOKEN or not config.WHATSAPP_PHONE_NUMBER_ID:
        logger.warning("WhatsApp credentials missing")
        return False

    url = f"https://graph.facebook.com/{config.WHATSAPP_API_VERSION}/{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {config.WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text[:4096]},  # WhatsApp limit
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        if r.status_code in (200, 201):
            return True
        logger.error("WhatsApp send failed: %s %s", r.status_code, r.text)
        return False
    except Exception as e:
        logger.error("WhatsApp send exception: %s", e)
        return False


def process_whatsapp_message(from_number: str, text: str, profile_name: str = "") -> None:
    """Core handler for incoming WhatsApp messages – reuses full gamification."""
    uid = from_number  # use phone number as unique ID
    udata = db.ensure_user(uid, full_name=profile_name or "Student", platform="whatsapp")
    is_pro = db.is_pro(uid)

    # Simple command detection
    lower = text.lower().strip()
    if lower in ("hi", "hello", "start", "menu", "/start", "/menu"):
        streak = db.update_streak(uid)
        msg = (
            f"🎓 *Welcome to StudyGenie by Sparsh Singhal!*\n\n"
            f"Namaste {profile_name or 'Champion'} 👋\n\n"
            f"India's most fun gamified AI tutor for JEE • NEET • GATE • Boards.\n\n"
            f"⭐ Level {udata.get('level', 1)} | XP {udata.get('xp', 0)}\n"
            f"🔥 Streak: {streak['current']} days\n\n"
            f"Just type any question and I will answer instantly!\n\n"
            f"_Created with ❤️ by Sparsh Singhal_"
        )
        send_whatsapp_message(from_number, msg)
        return

    if lower.startswith("/upgrade") or "upgrade" in lower or "pro" in lower:
        msg = (
            f"💎 *Unlock Pro – ₹{config.PRO_PRICE_INR} for 30 days*\n\n"
            "• Unlimited questions\n"
            "• Advanced tools & deeper AI\n"
            "• Priority responses\n"
            "• Exclusive badges\n\n"
            f"Pay here: https://{config.VERCEL_URL}/pay?uid={uid}\n\n"
            "Pro activates automatically after payment.\n\n"
            "_StudyGenie by Sparsh Singhal_"
        )
        send_whatsapp_message(from_number, msg)
        return

    # Quota check
    if not is_pro:
        can, quota = db.check_quota(uid)
        if not can:
            send_whatsapp_message(
                from_number,
                "❌ Daily / lifetime quota finished!\n\n"
                f"Upgrade to Pro for unlimited access: https://{config.VERCEL_URL}/pay?uid={uid}\n\n"
                "_StudyGenie by Sparsh Singhal_",
            )
            return

    # Detect tool
    if lower.startswith(("explain", "what is", "why", "how")):
        tool = "explain"
    elif lower.startswith(("solve", "calculate", "find")):
        tool = "solve"
    elif lower.startswith(("notes", "summarize")):
        tool = "notes"
    elif lower.startswith(("plan", "schedule")):
        tool = "planner"
    else:
        tool = "general"

    # Generate answer
    start = time.time()
    answer = ai.answer(text, tool, is_pro=is_pro)
    elapsed = time.time() - start

    if not answer:
        send_whatsapp_message(from_number, "😔 Couldn't generate answer right now. Please try again.\n\n_StudyGenie by Sparsh Singhal_")
        return

    if not is_pro:
        db.consume_quota(uid)

    xp, level = db.add_xp(uid, config.XP_QUESTION)
    questions = int(udata.get("questions_asked", 0)) + 1
    udata["questions_asked"] = str(questions)
    db.save_user(uid, udata)

    if questions == 1:
        db.add_badge(uid, "First Step 🐣")
    if questions >= 50:
        db.add_badge(uid, "Knowledge Seeker 📚")
    if level >= 5:
        db.add_badge(uid, "Rising Star ⭐")

    footer = (
        f"\n\n━━━━━━━━━━━━━━━\n"
        f"⚡ {elapsed:.1f}s | ⭐ +{config.XP_QUESTION} XP | Level {level}\n"
        f"_StudyGenie by Sparsh Singhal_"
    )
    full = answer + footer

    # WhatsApp has a soft limit; split if needed
    if len(full) <= 4000:
        send_whatsapp_message(from_number, full)
    else:
        for i in range(0, len(full), 3900):
            send_whatsapp_message(from_number, full[i:i+3900])


# ============================================================================
# TELEGRAM KEYBOARDS & HELPERS (unchanged logic)
# ============================================================================


def main_menu(is_pro: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("📚 Ask", callback_data="menu_ask"),
            InlineKeyboardButton("🎯 Quiz", callback_data="menu_quiz"),
        ],
        [
            InlineKeyboardButton("🛠 Tools", callback_data="menu_tools"),
            InlineKeyboardButton("📊 Progress", callback_data="menu_progress"),
        ],
        [
            InlineKeyboardButton("🏆 Leaderboard", callback_data="menu_lb"),
            InlineKeyboardButton("🔥 Streak", callback_data="menu_streak"),
        ],
        [
            InlineKeyboardButton("🎮 Daily Quest", callback_data="menu_quest"),
            InlineKeyboardButton("🏅 Badges", callback_data="menu_badges"),
        ],
    ]
    if not is_pro:
        rows.append([InlineKeyboardButton("💎 Upgrade to Pro – ₹49/mo", callback_data="menu_upgrade")])
    else:
        rows.append([InlineKeyboardButton("👑 Pro Active", callback_data="menu_prostatus")])
    rows.append([InlineKeyboardButton("👨‍💻 About Sparsh Singhal", callback_data="menu_about")])
    return InlineKeyboardMarkup(rows)


def tools_menu(is_pro: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("💡 Explain", callback_data="tool_explain"),
            InlineKeyboardButton("🧮 Solve", callback_data="tool_solve"),
        ],
        [
            InlineKeyboardButton("📝 Notes", callback_data="tool_notes"),
            InlineKeyboardButton("📋 PYQ", callback_data="tool_pyq"),
        ],
        [
            InlineKeyboardButton("📐 Formulas", callback_data="tool_formula"),
            InlineKeyboardButton("📅 Planner", callback_data="tool_planner"),
        ],
    ]
    if is_pro:
        rows.append([InlineKeyboardButton("🧪 Mock Test (Pro)", callback_data="tool_mock")])
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="menu_main")])
    return InlineKeyboardMarkup(rows)


async def reply(update: Update, text: str, markup=None) -> None:
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            await update.callback_query.message.reply_text(
                text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN
            )
    elif update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)


async def typing(update: Update) -> None:
    chat = update.effective_chat
    if chat:
        try:
            await chat.send_action(ChatAction.TYPING)
        except Exception:
            pass


async def process_question(update: Update, context: ContextTypes.DEFAULT_TYPE, q: str, tool: str = "general") -> None:
    user = update.effective_user
    if not user:
        return
    uid = user.id
    udata = db.ensure_user(uid, user.username or "", user.full_name or "Student", platform="telegram")
    is_pro = db.is_pro(uid)

    if not is_pro:
        can, quota = db.check_quota(uid)
        if not can:
            await reply(
                update,
                "❌ *Quota finished!*\n\nUpgrade to Pro for unlimited access + exclusive tools.\n\n"
                "_Powered by Sparsh Singhal_",
                InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade ₹49", callback_data="menu_upgrade")]]),
            )
            return

    await typing(update)
    start = time.time()
    answer = ai.answer(q, tool, is_pro=is_pro)
    elapsed = time.time() - start

    if not answer:
        await reply(update, "😔 Couldn't generate answer. Please try again.\n\n_StudyGenie by Sparsh Singhal_")
        return

    if not is_pro:
        db.consume_quota(uid)

    xp, level = db.add_xp(uid, config.XP_QUESTION)
    questions = int(udata.get("questions_asked", 0)) + 1
    udata["questions_asked"] = str(questions)
    db.save_user(uid, udata)

    if questions == 1:
        db.add_badge(uid, "First Step 🐣")
    if questions >= 50:
        db.add_badge(uid, "Knowledge Seeker 📚")
    if level >= 5:
        db.add_badge(uid, "Rising Star ⭐")

    footer = (
        f"\n\n━━━━━━━━━━━━━━━\n"
        f"⚡ {elapsed:.1f}s | ⭐ +{config.XP_QUESTION} XP | Level {level}\n"
        f"_StudyGenie by Sparsh Singhal_"
    )
    full = answer + footer

    if len(full) <= 4096:
        await reply(update, full)
    else:
        for i, chunk in enumerate([full[i:i+4000] for i in range(0, len(full), 4000)]):
            if i == 0:
                await reply(update, chunk)
            else:
                if update.message:
                    await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)


# Telegram handlers (abbreviated for brevity – full logic retained)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    db.ensure_user(user.id, user.username or "", user.full_name or "Student")
    is_pro = db.is_pro(user.id)
    await reply(
        update,
        f"🎓 *Welcome to StudyGenie by Sparsh Singhal*, {user.first_name or 'Champion'}!\n\n"
        "India's most fun *gamified* AI tutor for JEE • NEET • GATE • Boards.\n\n"
        "Also available on *WhatsApp*!\n\n"
        "Created with ❤️ by *Sparsh Singhal*\n\n"
        "Just type any question or open the menu 👇",
        main_menu(is_pro),
    )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    udata = db.ensure_user(user.id, user.username or "", user.full_name or "Student")
    streak = db.update_streak(user.id)
    is_pro = db.is_pro(user.id)
    _, quota = db.check_quota(user.id)

    text = (
        f"🎓 *StudyGenie by Sparsh Singhal*\n\n"
        f"👤 {udata.get('full_name')}\n"
        f"⭐ Level {udata.get('level', 1)} | XP {udata.get('xp', 0)}\n"
        f"🔥 Streak {streak['current']} days (🛡 {streak['shields']})\n"
    )
    if is_pro:
        text += "\n👑 *PRO ACTIVE*\n"
    else:
        text += f"\n❓ Questions left: {quota['daily_left']}\n"
    text += "\n*Choose:*\n\n_Made by Sparsh Singhal_"
    await reply(update, text, main_menu(is_pro))


async def free_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    lower = text.lower()
    if lower.startswith(("explain", "what is", "why", "how")):
        tool = "explain"
    elif lower.startswith(("solve", "calculate", "find")):
        tool = "solve"
    elif lower.startswith(("notes", "summarize")):
        tool = "notes"
    elif lower.startswith(("plan", "schedule")):
        tool = "planner"
    else:
        tool = "general"
    await process_question(update, context, text, tool)


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = " ".join(context.args).strip() if context.args else ""
    if q:
        await process_question(update, context, q)
    else:
        await reply(update, "Usage: `/ask your question`\n\n_StudyGenie by Sparsh Singhal_")


async def cmd_explain(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = " ".join(context.args).strip() if context.args else ""
    if q:
        await process_question(update, context, q, "explain")


async def cmd_solve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = " ".join(context.args).strip() if context.args else ""
    if q:
        await process_question(update, context, q, "solve")


async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    u = db.ensure_user(user.id)
    xp = int(u.get("xp", 0))
    level = int(u.get("level", 1))
    bar = "█" * (xp % 100 // 10) + "░" * (10 - xp % 100 // 10)
    await reply(
        update,
        f"📊 *Progress*\n\n"
        f"⭐ Level {level}\n"
        f"XP: {xp}\n`{bar}` {xp % 100}/100\n\n"
        f"🔥 Streak: {u.get('streak', 0)}\n"
        f"📚 Questions: {u.get('questions_asked', 0)}\n"
        f"🏅 Badges: {len(json.loads(u.get('badges', '[]')))}\n\n"
        f"_StudyGenie by Sparsh Singhal_",
    )


async def streak_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    s = db.update_streak(user.id)
    await reply(
        update,
        f"🔥 *Streak*\n\nCurrent: {s['current']} days\nBest: {s['best']}\nShields: {s['shields']}\n\n"
        "Come every day! Every 7 days you get a shield 🛡\n\n"
        "_Powered by Sparsh Singhal_",
    )


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    board = db.get_leaderboard(10)
    if not board:
        await reply(update, "🏆 Leaderboard empty. Be the first!\n\n_StudyGenie by Sparsh Singhal_")
        return
    lines = ["🏆 *Top Students*\n"]
    for e in board:
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(e["rank"], f"{e['rank']}.")
        lines.append(f"{medal} {e['name']} – Lvl {e['level']} ({e['xp']} XP)")
    rank = db.get_rank(update.effective_user.id)
    if rank:
        lines.append(f"\n📍 Your rank: #{rank}")
    lines.append("\n_StudyGenie by Sparsh Singhal_")
    await reply(update, "\n".join(lines))


async def upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reply(
        update,
        f"💎 *Unlock Pro – ₹{config.PRO_PRICE_INR} for 30 days*\n\n"
        "Features unlocked automatically after payment:\n"
        "• Unlimited questions\n"
        "• Mock tests, advanced planner, deeper AI\n"
        "• Priority queue + exclusive badges\n\n"
        f"Pay here: https://{config.VERCEL_URL}/pay?uid={update.effective_user.id}\n\n"
        "_StudyGenie by Sparsh Singhal_",
    )


async def about_sparsh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reply(
        update,
        "👨‍💻 *About the Creator*\n\n"
        "*Sparsh Singhal*\n"
        "Builder of StudyGenie – India's gamified AI tutor for JEE, NEET, GATE & Boards.\n\n"
        "Now available on Telegram + WhatsApp + Web!\n\n"
        "Passionate about making quality education fun and accessible for every Indian student.\n\n"
        "_StudyGenie by Sparsh Singhal_ ❤️",
    )


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q:
        return
    await q.answer()
    data = q.data or ""
    user = update.effective_user
    is_pro = db.is_pro(user.id) if user else False

    if data == "menu_main":
        await menu(update, context)
    elif data == "menu_ask":
        await reply(update, "📚 Type your question now!\n\n_StudyGenie by Sparsh Singhal_")
    elif data == "menu_quiz":
        await reply(update, "🎯 Quiz mode coming very soon!\n\n_Created by Sparsh Singhal_")
    elif data == "menu_tools":
        await reply(update, "🛠 *Study Tools*\n\n_StudyGenie by Sparsh Singhal_", tools_menu(is_pro))
    elif data == "menu_progress":
        await progress(update, context)
    elif data == "menu_lb":
        await leaderboard(update, context)
    elif data == "menu_streak":
        await streak_cmd(update, context)
    elif data == "menu_quest":
        quest = db.set_daily_quest(user.id)
        await reply(update, f"🎮 *Daily Quest*\n\n{quest}\n\n+{config.XP_DAILY_QUEST} XP\n\n_Sparsh Singhal_")
    elif data == "menu_badges":
        u = db.get_user(user.id) or {}
        badges = json.loads(u.get("badges", "[]"))
        text = "🏅 *Your Badges*\n\n" + ("\n".join(badges) if badges else "No badges yet.")
        text += "\n\n_StudyGenie by Sparsh Singhal_"
        await reply(update, text)
    elif data == "menu_upgrade":
        await upgrade(update, context)
    elif data == "menu_prostatus":
        u = db.get_user(user.id) or {}
        await reply(update, f"👑 Pro active until: {u.get('pro_until', 'N/A')[:10]}\n\n_Sparsh Singhal_")
    elif data == "menu_about":
        await about_sparsh(update, context)
    elif data.startswith("tool_"):
        tool = data.replace("tool_", "")
        await reply(update, f"✅ *{tool.title()}* selected. Type your question!\n\n_StudyGenie by Sparsh Singhal_")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Error: %s", context.error)


# ============================================================================
# TELEGRAM APPLICATION
# ============================================================================

telegram_app: Optional[Application] = None
_lock = asyncio.Lock()


async def get_app() -> Application:
    global telegram_app
    if telegram_app:
        return telegram_app
    async with _lock:
        if telegram_app:
            return telegram_app
        app = (
            ApplicationBuilder()
            .token(config.BOT_TOKEN)
            .defaults(Defaults(parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True))
            .build()
        )
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("menu", menu))
        app.add_handler(CommandHandler("ask", cmd_ask))
        app.add_handler(CommandHandler("explain", cmd_explain))
        app.add_handler(CommandHandler("solve", cmd_solve))
        app.add_handler(CommandHandler("progress", progress))
        app.add_handler(CommandHandler("streak", streak_cmd))
        app.add_handler(CommandHandler("leaderboard", leaderboard))
        app.add_handler(CommandHandler("upgrade", upgrade))
        app.add_handler(CommandHandler("about", about_sparsh))
        app.add_handler(CallbackQueryHandler(callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, free_text))
        app.add_error_handler(error_handler)
        await app.initialize()
        telegram_app = app
        return app


# ============================================================================
# FLASK APP
# ============================================================================

app = Flask(__name__)


@app.route("/sparsh.jpg")
def serve_photo():
    return send_from_directory(".", "sparsh.jpg")


FRONTEND_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>StudyGenie by Sparsh Singhal – Gamified AI Tutor</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
  :root { --bg: #0f172a; --card: #1e293b; --accent: #22d3ee; --text: #f1f5f9; --muted: #94a3b8; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; display: flex; flex-direction: column; }
  header { background: linear-gradient(90deg, #0ea5e9, #8b5cf6); padding: 1rem 1.5rem; display: flex; justify-content: space-between; align-items: center; }
  .logo { font-weight: 700; font-size: 1.25rem; }
  .badge { background: #22c55e; color: #000; padding: 0.25rem 0.6rem; border-radius: 999px; font-size: 0.75rem; font-weight: 600; }
  main { flex: 1; max-width: 800px; margin: 0 auto; width: 100%; padding: 1.5rem; }
  .creator { display: flex; align-items: center; gap: 1rem; background: var(--card); border-radius: 1rem; padding: 1rem; margin-bottom: 1rem; border: 1px solid #334155; }
  .creator img { width: 72px; height: 72px; border-radius: 50%; object-fit: cover; border: 3px solid #22d3ee; }
  .creator h3 { margin: 0; font-size: 1.1rem; }
  .creator p { margin: 0.2rem 0 0; color: var(--muted); font-size: 0.9rem; }
  .card { background: var(--card); border-radius: 1rem; padding: 1.25rem; margin-bottom: 1rem; border: 1px solid #334155; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 0.75rem; }
  .stat { text-align: center; }
  .stat strong { display: block; font-size: 1.4rem; color: var(--accent); }
  .chat-box { height: 360px; overflow-y: auto; background: #0f172a; border-radius: 0.75rem; padding: 1rem; margin-bottom: 1rem; border: 1px solid #334155; }
  .msg { margin-bottom: 0.75rem; max-width: 85%; }
  .msg.user { margin-left: auto; background: #0ea5e9; color: #fff; padding: 0.6rem 1rem; border-radius: 1rem 1rem 0 1rem; }
  .msg.bot { background: #334155; padding: 0.6rem 1rem; border-radius: 1rem 1rem 1rem 0; }
  .input-row { display: flex; gap: 0.5rem; }
  input { flex: 1; padding: 0.85rem 1rem; border-radius: 0.75rem; border: none; background: #1e293b; color: white; font-size: 1rem; }
  button { background: linear-gradient(90deg, #22d3ee, #0ea5e9); color: #0f172a; border: none; padding: 0 1.4rem; border-radius: 0.75rem; font-weight: 600; cursor: pointer; }
  .pro-btn { display: inline-block; margin-top: 0.75rem; background: linear-gradient(90deg, #f59e0b, #ef4444); color: white; padding: 0.6rem 1.2rem; border-radius: 0.75rem; text-decoration: none; font-weight: 600; }
  footer { text-align: center; padding: 1.5rem; color: var(--muted); font-size: 0.9rem; }
  footer strong { color: #22d3ee; }
</style>
</head>
<body>
<header>
  <div class="logo">🎓 StudyGenie by Sparsh Singhal</div>
  <div class="badge">Telegram • WhatsApp • Web</div>
</header>
<main>
  <div class="creator">
    <img src="/sparsh.jpg" alt="Sparsh Singhal" onerror="this.src='https://raw.githubusercontent.com/sparshsinghal2025-ops/studygenie/main/sparsh.jpg'">
    <div>
      <h3>Sparsh Singhal</h3>
      <p>Creator of StudyGenie • Now live on WhatsApp too!</p>
    </div>
  </div>
  <div class="card">
    <div class="stats">
      <div class="stat"><strong id="level">1</strong>Level</div>
      <div class="stat"><strong id="xp">0</strong>XP</div>
      <div class="stat"><strong id="streak">0</strong>Streak</div>
      <div class="stat"><strong id="rank">—</strong>Rank</div>
    </div>
  </div>
  <div class="card">
    <div class="chat-box" id="chat"></div>
    <div class="input-row">
      <input id="q" placeholder="Ask any JEE/NEET question..." autocomplete="off">
      <button onclick="ask()">Send</button>
    </div>
    <a class="pro-btn" href="/pay">💎 Unlock Pro – ₹{{ price }}/mo</a>
  </div>
</main>
<footer>
  <strong>StudyGenie by Sparsh Singhal</strong><br>
  Available on Telegram • WhatsApp • Web<br>
  Made with ❤️ for Indian students
</footer>
<script>
const chat = document.getElementById('chat');
function addMsg(text, who) {
  const d = document.createElement('div');
  d.className = 'msg ' + who;
  d.innerText = text;
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
}
async function ask() {
  const input = document.getElementById('q');
  const q = input.value.trim();
  if (!q) return;
  addMsg(q, 'user');
  input.value = '';
  addMsg('Thinking...', 'bot');
  try {
    const res = await fetch('/api/webask', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question: q})
    });
    const data = await res.json();
    chat.lastChild.innerText = data.answer || 'Error, try again';
  } catch(e) {
    chat.lastChild.innerText = 'Network error';
  }
}
document.getElementById('q').addEventListener('keypress', e => { if(e.key==='Enter') ask(); });
</script>
</body>
</html>
"""


@app.route("/")
def home():
    return render_template_string(FRONTEND_HTML, price=config.PRO_PRICE_INR)


@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "redis": db.redis is not None,
        "gemini": ai.client is not None,
        "whatsapp": bool(config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_NUMBER_ID),
        "version": "StudyGenie by Sparsh Singhal",
        "creator": "Sparsh Singhal",
    })


@app.route("/api/webask", methods=["POST"])
def web_ask():
    data = request.get_json(silent=True) or {}
    q = (data.get("question") or "").strip()
    if not q:
        return jsonify({"answer": "Please type a question"}), 400
    answer = ai.answer(q, "general", is_pro=False)
    if answer:
        answer += "\n\n— StudyGenie by Sparsh Singhal"
    return jsonify({"answer": answer or "Sorry, try again later."})


@app.route("/pay")
def pay_page():
    uid = request.args.get("uid", "0")
    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>Upgrade – StudyGenie by Sparsh Singhal</title>
    <style>
      body {{ font-family: Inter, sans-serif; background:#0f172a; color:white; text-align:center; padding:3rem; }}
      img {{ width:90px; height:90px; border-radius:50%; border:3px solid #22d3ee; margin-bottom:1rem; }}
      a {{ color:#22d3ee; }}
    </style></head>
    <body>
      <img src="/sparsh.jpg" alt="Sparsh Singhal" onerror="this.src='https://raw.githubusercontent.com/sparshsinghal2025-ops/studygenie/main/sparsh.jpg'">
      <h1>💎 StudyGenie Pro</h1>
      <p>Created by <strong>Sparsh Singhal</strong></p>
      <p>₹{config.PRO_PRICE_INR} for 30 days of unlimited power</p>
      <p>Works on Telegram + WhatsApp + Web</p>
      <p><small>User ID: {uid}</small></p>
      <p><a href="/">← Back</a></p>
    </body></html>
    """


@app.route("/api/razorpay/webhook", methods=["POST"])
def razorpay_webhook():
    try:
        payload = request.get_json(force=True)
        event = payload.get("event")
        if event == "payment.captured":
            notes = payload.get("payload", {}).get("payment", {}).get("entity", {}).get("notes", {})
            uid = notes.get("user_id", "")
            if uid:
                db.activate_pro(uid, days=30)
                db.add_badge(uid, "Pro Warrior 👑")
                logger.info("Pro activated for %s", uid)
        return jsonify({"ok": True})
    except Exception as e:
        logger.error("Razorpay webhook: %s", e)
        return jsonify({"ok": False}), 500


# ---------- WHATSAPP WEBHOOK ----------
@app.route("/api/whatsapp", methods=["GET", "POST"])
def whatsapp_webhook():
    # Verification (Meta requirement)
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == config.WHATSAPP_VERIFY_TOKEN:
            logger.info("WhatsApp webhook verified")
            return challenge, 200
        return "Forbidden", 403

    # Incoming messages
    try:
        data = request.get_json(force=True, silent=True) or {}
        entry = data.get("entry", [])
        if not entry:
            return jsonify({"ok": True})

        for ent in entry:
            changes = ent.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])
                contacts = value.get("contacts", [])

                profile_name = ""
                if contacts:
                    profile_name = contacts[0].get("profile", {}).get("name", "")

                for msg in messages:
                    if msg.get("type") != "text":
                        continue
                    from_number = msg.get("from")
                    text = msg.get("text", {}).get("body", "").strip()
                    if from_number and text:
                        # Process in background-friendly way
                        process_whatsapp_message(from_number, text, profile_name)

        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("WhatsApp webhook error: %s", e)
        return jsonify({"ok": False}), 500


@app.route("/api/webhook", methods=["POST"])
def telegram_webhook():
    if config.WEBHOOK_SECRET:
        if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != config.WEBHOOK_SECRET:
            return jsonify({"ok": False}), 401
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"ok": False}), 400

        async def _run():
            application = await get_app()
            update = Update.de_json(data, application.bot)
            if update:
                await application.process_update(update)

        asyncio.run(_run())
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("Telegram webhook: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/setup")
def setup():
    if not config.VERCEL_URL:
        return jsonify({"error": "VERCEL_URL missing"}), 400
    url = f"https://{config.VERCEL_URL}/api/webhook"

    async def _set():
        application = await get_app()
        kwargs = {"url": url}
        if config.WEBHOOK_SECRET:
            kwargs["secret_token"] = config.WEBHOOK_SECRET
        await application.bot.set_webhook(**kwargs)
        return url

    try:
        u = asyncio.run(_set())
        return jsonify({
            "ok": True,
            "telegram_webhook": u,
            "whatsapp_webhook": f"https://{config.VERCEL_URL}/api/whatsapp",
            "creator": "Sparsh Singhal",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
