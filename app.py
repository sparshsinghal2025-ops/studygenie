"""
StudyGenie by Sparsh Singhal
Fully Gamified Multi-Platform E-Learning Bot
Telegram + WhatsApp + Web Dashboard
Production-ready (thousands scale) for Railway / Render / Fly / VPS

Author & Creator: Sparsh Singhal
Updated: Groq (Primary) + Gemini (Fallback) | All Exams Support
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
from collections import defaultdict
from datetime import datetime, timedelta
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import redis
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request, render_template_string, send_from_directory
from google import genai
from google.genai import types as genai_types
from groq import Groq
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


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("studygenie")


class Config:
    def __init__(self) -> None:
        self.BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
        self.VERCEL_URL = os.getenv("VERCEL_URL", "").strip()
        self.WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()

        self.REDIS_URL = (os.getenv("REDIS_URL") or os.getenv("UPSTASH_REDIS_URL") or "").strip()

        # AI
        self.GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()
        self.GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()
        self.GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
        self.GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip()
        self.AI_PRIMARY = os.getenv("AI_PRIMARY", "groq").strip().lower()

        self.FREE_DAILY = int(os.getenv("FREE_DAILY_QUESTIONS", "8"))
        self.FREE_LIFETIME = int(os.getenv("FREE_LIFETIME_QUESTIONS", "25"))

        self.PRO_PRICE_INR = int(os.getenv("PRO_PRICE_INR", "49"))
        self.RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "").strip()
        self.RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
        self.RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "").strip()

        self.WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "").strip()
        self.WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
        self.WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "studygenie_sparsh").strip()
        self.WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v20.0")

        self.XP_QUESTION = 15
        self.XP_QUIZ = 25
        self.XP_DAILY_QUEST = 40
        self.XP_REFERRAL = 100
        self.CACHE_TTL = 3600

        self.DEV_SECRET = os.getenv("DEV_SECRET", "SPARSH2025").strip()

        self.validate()

    def validate(self) -> None:
        if not self.BOT_TOKEN:
            logger.error("BOT_TOKEN is missing")
        if not self.GROQ_API_KEY and not self.GOOGLE_API_KEY:
            logger.error("Neither GROQ_API_KEY nor GOOGLE_API_KEY is set!")
        if not self.GROQ_API_KEY:
            logger.warning("GROQ_API_KEY missing – will rely only on Gemini")
        if not self.GOOGLE_API_KEY:
            logger.warning("GOOGLE_API_KEY missing – will rely only on Groq")


config = Config()

# ============================================================================
# INFRA
# ============================================================================

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

_AI_POOL = ThreadPoolExecutor(max_workers=int(os.getenv("AI_POOL_WORKERS", "8")), thread_name_prefix="ai")
_AI_TIMEOUT = float(os.getenv("AI_TIMEOUT_SEC", "55"))

_rate_lock = Lock()
_rate_buckets: dict[str, list[float]] = defaultdict(list)
_redis_for_rl: Optional[redis.Redis] = None


def is_rate_limited(key: str, max_calls: int = 12, window_sec: int = 60) -> bool:
    r = _redis_for_rl
    if r is not None:
        try:
            rk = f"rl:{key}"
            now = time.time()
            pipe = r.pipeline()
            pipe.zremrangebyscore(rk, 0, now - window_sec)
            pipe.zcard(rk)
            pipe.zadd(rk, {f"{now}:{secrets.token_hex(3)}": now})
            pipe.expire(rk, window_sec + 5)
            results = pipe.execute()
            count = int(results[1] or 0)
            return count >= max_calls
        except Exception as e:
            logger.warning("Redis rate-limit fallback: %s", e)

    now = time.time()
    with _rate_lock:
        bucket = _rate_buckets[key]
        while bucket and bucket[0] <= now - window_sec:
            bucket.pop(0)
        if len(bucket) >= max_calls:
            return True
        bucket.append(now)
        return False


def run_ai(fn, *args, **kwargs):
    fut = _AI_POOL.submit(fn, *args, **kwargs)
    try:
        result = fut.result(timeout=_AI_TIMEOUT)
        if result is None:
            return "ERROR: AI returned empty response."
        return result
    except FuturesTimeout:
        logger.error("AI call timed out after %ss", _AI_TIMEOUT)
        return f"ERROR: AI timed out after {_AI_TIMEOUT:.0f}s."
    except Exception as e:
        logger.error("AI pool error: %s", e)
        return f"ERROR: {e}"


# ============================================================================
# DATABASE
# ============================================================================

class Database:
    def __init__(self) -> None:
        self.redis = self._connect()

    def _connect(self) -> Optional[redis.Redis]:
        if not config.REDIS_URL:
            logger.warning("No Redis – limited mode")
            return None
        try:
            pool = redis.ConnectionPool.from_url(
                config.REDIS_URL,
                decode_responses=True,
                max_connections=int(os.getenv("REDIS_MAX_CONN", "40")),
                socket_timeout=5,
                socket_connect_timeout=5,
                socket_keepalive=True,
                retry_on_timeout=True,
                health_check_interval=30,
            )
            r = redis.Redis(connection_pool=pool)
            r.ping()
            logger.info("Redis OK")
            return r
        except Exception as e:
            logger.error("Redis fail: %s", e)
            return None

    def set_tool(self, uid: str | int, tool: str, ttl: int = 300) -> None:
        if self.redis:
            try:
                self.redis.setex(f"tool:{uid}", ttl, tool)
            except Exception:
                pass

    def pop_tool(self, uid: str | int) -> Optional[str]:
        if not self.redis:
            return None
        try:
            key = f"tool:{uid}"
            tool = self.redis.get(key)
            if tool:
                self.redis.delete(key)
            return tool
        except Exception:
            return None

    def mark_payment_processed(self, payment_id: str) -> bool:
        if not self.redis or not payment_id:
            return True
        try:
            return bool(self.redis.set(f"pay:done:{payment_id}", "1", nx=True, ex=86400 * 90))
        except Exception:
            return True

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
            if self.redis:
                try:
                    self.redis.sadd("stats:users", str(uid))
                except Exception:
                    pass
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
        if self.redis:
            try:
                self.redis.sadd("stats:users", str(uid))
                self.redis.incr("stats:total_questions")
            except Exception:
                pass
        return data

    def is_pro(self, uid: str | int) -> bool:
        user = self.get_user(uid)
        if not user or user.get("plan") != "pro":
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
        user.update({"streak": str(new), "best_streak": str(best), "shields": str(shields), "last_activity": today})
        self.save_user(uid, user)
        return {"current": new, "best": best, "shields": shields}

    def check_quota(self, uid: str | int) -> Tuple[bool, Dict[str, int]]:
        if self.is_pro(uid):
            return True, {"daily_left": -1, "lifetime_left": -1}
        if not self.redis:
            return True, {"daily_left": config.FREE_DAILY, "lifetime_left": config.FREE_LIFETIME}
        try:
            today = _today_ist()
            daily_used = int(self.redis.get(f"quota:daily:{uid}:{today}") or 0)
            life_used = int(self.redis.get(f"quota:lifetime:{uid}") or 0)
            daily_left = max(0, config.FREE_DAILY - daily_used)
            life_left = max(0, config.FREE_LIFETIME - life_used)
            return (daily_left > 0 and life_left > 0), {"daily_left": daily_left, "lifetime_left": life_left}
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

    def get_leaderboard(self, limit: int = 15) -> List[Dict]:
        if not self.redis:
            return []
        try:
            top = self.redis.zrevrange("leaderboard", 0, limit - 1, withscores=True)
            out = []
            for rank, (uid, xp) in enumerate(top, 1):
                u = self.get_user(uid)
                out.append({
                    "rank": rank,
                    "name": (u or {}).get("full_name", "Student")[:20],
                    "xp": int(xp),
                    "level": int((u or {}).get("level", 1)),
                    "platform": (u or {}).get("platform", "web"),
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

    def get_stats(self) -> Dict[str, int]:
        if not self.redis:
            return {"total_users": 0, "total_questions": 0, "online_approx": 0}
        try:
            return {
                "total_users": int(self.redis.scard("stats:users") or 0),
                "total_questions": int(self.redis.get("stats:total_questions") or 0),
                "online_approx": int(self.redis.zcard("leaderboard") or 0),
            }
        except Exception:
            return {"total_users": 0, "total_questions": 0, "online_approx": 0}


db = Database()
_redis_for_rl = db.redis

# ============================================================================
# AI SERVICE (Groq Primary + Gemini Fallback) - All Exams Support
# ============================================================================

class AIService:
    def __init__(self) -> None:
        self.gemini_client = None
        self.groq_client = None

        if config.GOOGLE_API_KEY:
            try:
                self.gemini_client = genai.Client(api_key=config.GOOGLE_API_KEY)
                logger.info("Gemini client ready")
            except Exception as e:
                logger.error("Gemini init failed: %s", e)

        if config.GROQ_API_KEY:
            try:
                self.groq_client = Groq(api_key=config.GROQ_API_KEY)
                logger.info("Groq client ready | model=%s", config.GROQ_MODEL)
            except Exception as e:
                logger.error("Groq init failed: %s", e)

    def _base_prompt(self, is_pro: bool) -> str:
        base = (
            "You are StudyGenie by Sparsh Singhal – India's most fun, friendly and powerful gamified AI tutor. "
            "You help students of all levels: Class 6 to 12 Boards, JEE, NEET, GATE, UPSC, SSC, Banking, CA, CUET, "
            "State Board exams, Olympiads and more. Created with ❤️ by Sparsh Singhal.\n\n"
            "Reply in natural Hinglish (mix of Hindi + English) unless the student asks for pure English or pure Hindi. "
            "Be encouraging, use emojis, explain step-by-step, and keep answers clear, exam-oriented and easy to understand.\n\n"
        )
        if is_pro:
            base += (
                "This user is PRO. Give deeper explanations, extra tips, memory tricks, common mistakes, "
                "exam strategy and one bonus question when useful.\n\n"
            )
        return base

    def _templates(self, base: str, question: str) -> Dict[str, str]:
        return {
            "general": f"{base}Student's Question:\n{question}",
            "explain": f"{base}Explain this concept simply with examples, analogy and real-life connection.\n\n{question}",
            "solve": f"{base}Solve step-by-step with full working, units (if any), and final clear answer.\n\n{question}",
            "notes": f"{base}Create short, exam-ready notes + key points + important formulas/one-liners.\n\n{question}",
            "pyq": f"{base}Solve this Previous Year Question carefully. Show full working and give similar question tip.\n\n{question}",
            "formula": f"{base}List all important formulas/concepts with short notes and when to use them.\n\n{question}",
            "planner": f"{base}Create a realistic 7-day study plan with daily targets and revision slots.\n\nTopic/Goal: {question}",
            "mock": f"{base}Generate 5 high-quality MCQs with options, correct answer and short explanation.\n\nTopic: {question}",
            "roast": f"{base}Hinglish Savage but Educational Roast Mode. Roast the doubt/common mistakes in a fun motivational way while teaching the correct concept.\n\nDoubt: {question}",
            "ncert": f"{base}Give complete NCERT-style clear explanation suitable for Boards + competitive exams.\n\n{question}",
            "mindmap": f"{base}Create a clear hierarchical text mind-map (use indentation and bullets).\n\nTopic: {question}",
            "important": f"{base}Generate 10-12 high-yield Important Questions with short answers/hints.\n\nTopic: {question}",
            "diagram": f"{base}Explain the diagram/figure in detail – every labelled part and exam-relevant points.\n\n{question}",
            "derivation": f"{base}Give full step-by-step derivation/proof with reasoning.\n\n{question}",
            "numerical": f"{base}Numerical Solver: Complete steps, formula, substitution, calculation and final answer with units.\n\n{question}",
            "mcq": f"{base}Create 8 high-quality MCQs (mix of easy-medium-hard) with options, answer and short explanation.\n\nTopic: {question}",
            "essay": f"{base}Write a well-structured essay / letter / application / formal writing as requested.\n\nRequest: {question}",
            "resume": f"{base}Create or improve a clean, modern student resume/CV (ATS friendly).\n\nDetails: {question}",
            "youtube": f"{base}YouTube-style summary: key points + important concepts + 5 revision questions.\n\nTopic: {question}",
            "career": f"{base}Give practical career guidance for Indian students (all streams).\n\nQuery: {question}",
            "tips": f"{base}Sparsh Singhal Direct Tips mode: Sharp study tips, CODE strategy, exam psychology and motivation.\n\nTopic: {question}",
            "voice": f"{base}Give a short, natural spoken-style answer easy to read aloud.\n\n{question}",
            "ocr": f"{base}Image/OCR mode: First read the question from image accurately, then solve completely.\n\nExtra text: {question}",
        }

    def _call_groq(self, prompt: str, max_tokens: int = 1800) -> Optional[str]:
        if not self.groq_client:
            return None
        try:
            resp = self.groq_client.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": "You are StudyGenie by Sparsh Singhal – a helpful, encouraging AI tutor for all Indian exams. Reply in natural Hinglish."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.35,
                max_tokens=max_tokens,
                timeout=45,
            )
            text = (resp.choices[0].message.content or "").strip()
            return text if text else None
        except Exception as e:
            logger.warning("Groq error: %s", e)
            return None

    def _call_gemini(self, prompt: str, max_tokens: int = 1800) -> Optional[str]:
        if not self.gemini_client:
            return None
        models_to_try = [config.GEMINI_MODEL, "gemini-2.0-flash", "gemini-1.5-flash"]
        for model_name in models_to_try:
            try:
                resp = self.gemini_client.models.generate_content(
                    model=model_name,
                    contents=[prompt],
                    config=genai_types.GenerateContentConfig(
                        temperature=0.35,
                        max_output_tokens=max_tokens,
                    ),
                )
                text = (resp.text or "").strip()
                if text:
                    if model_name != config.GEMINI_MODEL:
                        logger.info("Gemini fallback model used: %s", model_name)
                    return text
            except Exception as e:
                logger.warning("Gemini %s error: %s", model_name, e)
                continue
        return None

    def answer(self, question: str, tool: str = "general", is_pro: bool = False) -> Optional[str]:
        if not self.groq_client and not self.gemini_client:
            return "😔 AI service temporarily unavailable. Please try again in a minute.\n\n_ - made with love by Sparsh Singhal _"

        cache_key = f"ai:{tool}:{hashlib.md5(question.lower().encode()).hexdigest()}"
        if db.redis:
            try:
                cached = db.redis.get(cache_key)
                if cached:
                    return cached
            except Exception:
                pass

        base = self._base_prompt(is_pro)
        templates = self._templates(base, question)
        prompt = templates.get(tool, templates["general"])
        max_tokens = 2800 if is_pro else 1600

        providers = [("groq", self._call_groq), ("gemini", self._call_gemini)] if config.AI_PRIMARY == "groq" else [("gemini", self._call_gemini), ("groq", self._call_groq)]

        text = None
        for name, fn in providers:
            text = fn(prompt, max_tokens=max_tokens)
            if text:
                logger.info("AI success via %s | tool=%s", name, tool)
                break

        if not text:
            return "😔 Thoda technical issue aa gaya. Please 10-15 second baad try karo.\n\n_ - made with love by Sparsh Singhal _"

        if db.redis and text:
            try:
                db.redis.setex(cache_key, config.CACHE_TTL, text)
            except Exception:
                pass
        return text

    def answer_with_image(self, image_bytes: bytes, mime_type: str = "image/jpeg", question: str = "", tool: str = "ocr", is_pro: bool = False) -> Optional[str]:
        if not is_pro:
            return f"📷 Image Doubt Scan is Pro-only.\n\nUpgrade for ₹{config.PRO_PRICE_INR}/30 days.\n\n- made with love by Sparsh Singhal"

        if not self.gemini_client:
            return "📷 Image feature temporarily unavailable. Please try again later.\n\n_ - made with love by Sparsh Singhal _"

        base = self._base_prompt(is_pro)
        extra = question.strip() or "Solve the question shown in the image completely."
        prompt = f"{base}You can SEE the image. Do accurate OCR first, then solve step-by-step.\n\nUser note: {extra}"

        try:
            part = genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            resp = self.gemini_client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=[part, prompt],
                config=genai_types.GenerateContentConfig(temperature=0.3, max_output_tokens=3000),
            )
            text = (resp.text or "").strip()
            if text:
                return text
        except Exception as e:
            logger.error("Gemini vision error: %s", e)

        return self.answer(f"[Image OCR failed] {extra}", tool="ocr", is_pro=is_pro)


ai = AIService()

# ============================================================================
# WHATSAPP
# ============================================================================

def send_whatsapp_message(to: str, text: str) -> bool:
    if not config.WHATSAPP_TOKEN or not config.WHATSAPP_PHONE_NUMBER_ID:
        return False
    url = f"https://graph.facebook.com/{config.WHATSAPP_API_VERSION}/{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text[:4096]}}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        return r.status_code in (200, 201)
    except Exception as e:
        logger.error("WhatsApp error: %s", e)
        return False


def process_whatsapp_message(from_number: str, text: str, profile_name: str = "") -> None:
    uid = from_number
    if is_rate_limited(f"wa:{uid}", max_calls=15, window_sec=60):
        send_whatsapp_message(from_number, "Too many messages. Please wait a minute.\n\n_ - made with love by Sparsh Singhal _")
        return

    udata = db.ensure_user(uid, full_name=profile_name or "Student", platform="whatsapp")
    is_pro = db.is_pro(uid)
    lower = text.lower().strip()

    if lower in ("hi", "hello", "start", "menu", "/start", "/menu"):
        streak = db.update_streak(uid)
        _, quota = db.check_quota(uid)
        msg = (
            f"🎓 *Welcome to StudyGenie by Sparsh Singhal!*\n\n"
            f"Namaste {profile_name or 'Champion'} 👋\n\n"
            f"All-in-one AI tutor for Boards • JEE • NEET • GATE • UPSC • SSC • Banking • CA & more.\n\n"
            f"⭐ Level {udata.get('level', 1)} | XP {udata.get('xp', 0)}\n"
            f"🔥 Streak: {streak['current']} days\n\n"
        )
        if not is_pro:
            msg += f"🆓 Free: *{quota['daily_left']}* left today | *{quota['lifetime_left']}* lifetime\n\n"
        msg += "Just type any question!\n\n_ - made with love by Sparsh Singhal _"
        send_whatsapp_message(from_number, msg)
        return

    if "upgrade" in lower or "pro" in lower:
        send_whatsapp_message(
            from_number,
            f"💎 *Unlock Pro – ₹{config.PRO_PRICE_INR}/30 days*\n\n"
            f"Unlimited doubts + all 28 Pro tools\n\n"
            f"Pay: https://{config.VERCEL_URL}/pay?uid={uid}\n\n"
            f"_ - made with love by Sparsh Singhal _"
        )
        return

    if not is_pro:
        can, quota = db.check_quota(uid)
        if not can:
            send_whatsapp_message(from_number, f"❌ Quota finished!\n\nUpgrade: https://{config.VERCEL_URL}/pay?uid={uid}\n\n_ - made with love by Sparsh Singhal _")
            return

    # Simple tool detection
    tool = "general"
    if lower.startswith(("explain", "what is", "why", "how")): tool = "explain"
    elif lower.startswith(("solve", "calculate", "find")): tool = "solve"
    elif lower.startswith(("notes", "summarize")): tool = "notes"
    elif lower.startswith(("plan", "schedule")): tool = "planner"
    elif lower.startswith(("roast", "savage")): tool = "roast"
    elif lower.startswith(("mindmap", "mind map")): tool = "mindmap"
    elif lower.startswith(("derivation", "derive")): tool = "derivation"
    elif lower.startswith(("numerical",)): tool = "numerical"
    elif lower.startswith(("mcq", "quiz")): tool = "mcq"
    elif lower.startswith(("essay", "letter")): tool = "essay"
    elif lower.startswith(("resume", "cv")): tool = "resume"
    elif lower.startswith(("career",)): tool = "career"
    elif lower.startswith(("tips", "sparsh")): tool = "tips"
    elif lower.startswith(("ncert",)): tool = "ncert"

    pro_only = {"roast", "ncert", "mindmap", "important", "diagram", "derivation", "numerical", "mcq", "essay", "resume", "youtube", "career", "voice", "ocr", "mock", "tips"}
    if tool in pro_only and not is_pro:
        send_whatsapp_message(from_number, f"🔒 *{tool.title()}* is Pro-only.\n\nUpgrade: https://{config.VERCEL_URL}/pay?uid={uid}\n\n_ - made with love by Sparsh Singhal _")
        return

    start = time.time()
    answer = run_ai(ai.answer, text, tool, is_pro=is_pro)
    elapsed = time.time() - start

    if not answer or str(answer).startswith("ERROR:"):
        send_whatsapp_message(from_number, "😔 Couldn't generate answer. Please try again.\n\n_ - made with love by Sparsh Singhal _")
        return

    if not is_pro:
        db.consume_quota(uid)

    xp_gain = config.XP_QUESTION * (2 if is_pro else 1)
    xp, level = db.add_xp(uid, xp_gain)
    questions = int(udata.get("questions_asked", 0)) + 1
    udata["questions_asked"] = str(questions)
    db.save_user(uid, udata)

    if questions == 1: db.add_badge(uid, "First Step 🐣")
    if questions >= 50: db.add_badge(uid, "Knowledge Seeker 📚")
    if level >= 5: db.add_badge(uid, "Rising Star ⭐")

    footer = f"\n\n━━━━━━━━━━━━━━━\n⚡ {elapsed:.1f}s | ⭐ +{xp_gain} XP{' (2× Pro)' if is_pro else ''} | Level {level}\n_ - made with love by Sparsh Singhal _"
    full = answer + footer
    if len(full) <= 4000:
        send_whatsapp_message(from_number, full)
    else:
        for i in range(0, len(full), 3900):
            send_whatsapp_message(from_number, full[i:i+3900])


# ============================================================================
# TELEGRAM HELPERS
# ============================================================================

def main_menu(is_pro: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📚 Ask", callback_data="menu_ask"), InlineKeyboardButton("🎯 Quiz", callback_data="menu_quiz")],
        [InlineKeyboardButton("🛠 Tools", callback_data="menu_tools"), InlineKeyboardButton("📊 Progress", callback_data="menu_progress")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="menu_lb"), InlineKeyboardButton("🔥 Streak", callback_data="menu_streak")],
        [InlineKeyboardButton("🎮 Daily Quest", callback_data="menu_quest"), InlineKeyboardButton("🏅 Badges", callback_data="menu_badges")],
    ]
    if not is_pro:
        rows.append([InlineKeyboardButton(f"💎 Upgrade to Pro – ₹{config.PRO_PRICE_INR}/mo", callback_data="menu_upgrade")])
    else:
        rows.append([InlineKeyboardButton("👑 Pro Active", callback_data="menu_prostatus")])
    rows.append([InlineKeyboardButton("👨‍💻 About Sparsh Singhal", callback_data="menu_about")])
    return InlineKeyboardMarkup(rows)


def tools_menu(is_pro: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("💡 Explain", callback_data="tool_explain"), InlineKeyboardButton("🧮 Solve", callback_data="tool_solve")],
        [InlineKeyboardButton("📝 Notes", callback_data="tool_notes"), InlineKeyboardButton("📋 PYQ", callback_data="tool_pyq")],
        [InlineKeyboardButton("📐 Formulas", callback_data="tool_formula"), InlineKeyboardButton("📅 Planner", callback_data="tool_planner")],
    ]
    if is_pro:
        rows.extend([
            [InlineKeyboardButton("🔥 Savage Roast", callback_data="tool_roast"), InlineKeyboardButton("📖 NCERT Mode", callback_data="tool_ncert")],
            [InlineKeyboardButton("🧠 Mind Map", callback_data="tool_mindmap"), InlineKeyboardButton("⭐ Important Qs", callback_data="tool_important")],
            [InlineKeyboardButton("🖼 Diagram", callback_data="tool_diagram"), InlineKeyboardButton("📐 Derivation", callback_data="tool_derivation")],
            [InlineKeyboardButton("🔢 Numerical", callback_data="tool_numerical"), InlineKeyboardButton("🧪 MCQ Quiz", callback_data="tool_mcq")],
            [InlineKeyboardButton("📝 Essay/Letter", callback_data="tool_essay"), InlineKeyboardButton("📄 Resume", callback_data="tool_resume")],
            [InlineKeyboardButton("🎬 YT Summary", callback_data="tool_youtube"), InlineKeyboardButton("🎯 Career Guide", callback_data="tool_career")],
            [InlineKeyboardButton("🎤 Voice Style", callback_data="tool_voice"), InlineKeyboardButton("📷 Image/OCR", callback_data="tool_ocr")],
            [InlineKeyboardButton("🧪 Mock Test", callback_data="tool_mock"), InlineKeyboardButton("💡 Sparsh Tips", callback_data="tool_tips")],
        ])
    else:
        rows.append([InlineKeyboardButton("🔒 Unlock 20+ Pro Tools", callback_data="menu_upgrade")])
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="menu_main")])
    return InlineKeyboardMarkup(rows)


async def reply(update: Update, text: str, markup=None) -> None:
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await update.callback_query.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    elif update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)


async def typing(update: Update) -> None:
    if update.effective_chat:
        try:
            await update.effective_chat.send_action(ChatAction.TYPING)
        except Exception:
            pass


async def process_question(update: Update, context: ContextTypes.DEFAULT_TYPE, q: str, tool: str = "general") -> None:
    user = update.effective_user
    if not user:
        return
    uid = user.id
    udata = db.ensure_user(uid, user.username or "", user.full_name or "Student", platform="telegram")
    is_pro = db.is_pro(uid)

    pro_only = {"roast", "ncert", "mindmap", "important", "diagram", "derivation", "numerical", "mcq", "essay", "resume", "youtube", "career", "voice", "ocr", "mock", "tips"}
    if tool in pro_only and not is_pro:
        await reply(update, f"🔒 *{tool.title()}* is Pro-only.\n\nUpgrade for ₹{config.PRO_PRICE_INR}/30 days.\n\n_ - made with love by Sparsh Singhal _",
                    InlineKeyboardMarkup([[InlineKeyboardButton(f"💎 Upgrade ₹{config.PRO_PRICE_INR}", callback_data="menu_upgrade")]]))
        return

    if not is_pro:
        can, _ = db.check_quota(uid)
        if not can:
            await reply(update, f"❌ *Quota finished!*\n\nUpgrade to Pro for unlimited access.\n\n_ - made with love by Sparsh Singhal _",
                        InlineKeyboardMarkup([[InlineKeyboardButton(f"💎 Upgrade ₹{config.PRO_PRICE_INR}", callback_data="menu_upgrade")]]))
            return

    await typing(update)
    start = time.time()
    answer = run_ai(ai.answer, q, tool, is_pro=is_pro)
    elapsed = time.time() - start

    if not answer or str(answer).startswith("ERROR:"):
        await reply(update, "😔 Couldn't generate answer. Please try again in a few seconds.\n\n_ - made with love by Sparsh Singhal _")
        return

    if not is_pro:
        db.consume_quota(uid)

    xp_gain = config.XP_QUESTION * (2 if is_pro else 1)
    xp, level = db.add_xp(uid, xp_gain)
    questions = int(udata.get("questions_asked", 0)) + 1
    udata["questions_asked"] = str(questions)
    db.save_user(uid, udata)

    if questions == 1: db.add_badge(uid, "First Step 🐣")
    if questions >= 50: db.add_badge(uid, "Knowledge Seeker 📚")
    if level >= 5: db.add_badge(uid, "Rising Star ⭐")

    footer = f"\n\n━━━━━━━━━━━━━━━\n⚡ {elapsed:.1f}s | ⭐ +{xp_gain} XP{' (2× Pro)' if is_pro else ''} | Level {level}\n_ - made with love by Sparsh Singhal _"
    full = answer + footer
    if len(full) <= 4096:
        await reply(update, full)
    else:
        for i, chunk in enumerate([full[i:i+4000] for i in range(0, len(full), 4000)]):
            if i == 0:
                await reply(update, chunk)
            elif update.message:
                await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)


# ====================== TELEGRAM HANDLERS ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user: return
    db.ensure_user(user.id, user.username or "", user.full_name or "Student")
    is_pro = db.is_pro(user.id)
    _, quota = db.check_quota(user.id)
    text = (
        f"🎓 *Welcome to StudyGenie by Sparsh Singhal*, {user.first_name or 'Champion'}!\n\n"
        "All-in-one gamified AI tutor for **Boards • JEE • NEET • GATE • UPSC • SSC • Banking • CA • CUET** and more.\n\n"
    )
    if not is_pro:
        text += f"🆓 Free: *{quota['daily_left']}* left today | *{quota['lifetime_left']}* lifetime\n\n"
    text += "Created with ❤️ by *Sparsh Singhal*\n\nJust type any question or open the menu 👇"
    await reply(update, text, main_menu(is_pro))


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user: return
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
        text += f"\n❓ Left today: {quota['daily_left']} | Lifetime: {quota['lifetime_left']}\n"
    text += "\n*Choose:*\n\n_ - made with love by Sparsh Singhal _"
    await reply(update, text, main_menu(is_pro))


async def free_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text: return
    text = update.message.text.strip()
    lower = text.lower()
    selected = db.pop_tool(update.effective_user.id) if update.effective_user else None
    if not selected and context.user_data:
        selected = context.user_data.pop("selected_tool", None)

    tool = selected or "general"
    if not selected:
        if lower.startswith(("explain", "what is", "why", "how")): tool = "explain"
        elif lower.startswith(("solve", "calculate", "find")): tool = "solve"
        elif lower.startswith(("notes", "summarize")): tool = "notes"
        elif lower.startswith(("plan", "schedule")): tool = "planner"
        elif lower.startswith(("roast", "savage")): tool = "roast"
        elif lower.startswith(("mindmap", "mind map")): tool = "mindmap"
        elif lower.startswith(("derivation", "derive")): tool = "derivation"
        elif lower.startswith(("numerical",)): tool = "numerical"
        elif lower.startswith(("mcq", "quiz")): tool = "mcq"
        elif lower.startswith(("essay", "letter")): tool = "essay"
        elif lower.startswith(("resume", "cv")): tool = "resume"
        elif lower.startswith(("career",)): tool = "career"
        elif lower.startswith(("tips", "sparsh")): tool = "tips"
        elif lower.startswith(("ncert",)): tool = "ncert"

    await process_question(update, context, text, tool)


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = " ".join(context.args).strip() if context.args else ""
    if q:
        await process_question(update, context, q)
    else:
        await reply(update, "Usage: `/ask your question`\n\n_ - made with love by Sparsh Singhal _")


async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user: return
    u = db.ensure_user(user.id)
    xp = int(u.get("xp", 0))
    level = int(u.get("level", 1))
    bar = "█" * (xp % 100 // 10) + "░" * (10 - xp % 100 // 10)
    await reply(update, f"📊 *Progress*\n\n⭐ Level {level}\nXP: {xp}\n`{bar}` {xp % 100}/100\n\n🔥 Streak: {u.get('streak', 0)}\n📚 Questions: {u.get('questions_asked', 0)}\n\n_ - made with love by Sparsh Singhal _")


async def streak_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user: return
    s = db.update_streak(user.id)
    await reply(update, f"🔥 *Streak*\n\nCurrent: {s['current']} days\nBest: {s['best']}\nShields: {s['shields']}\n\nCome every day! Every 7 days you get a shield 🛡\n\n_ - made with love by Sparsh Singhal _")


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    board = db.get_leaderboard(15)
    if not board:
        await reply(update, "🏆 Leaderboard empty. Be the first!\n\n_ - made with love by Sparsh Singhal _")
        return
    lines = ["🏆 *Live Leaderboard (by XP)*\n"]
    for e in board:
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(e["rank"], f"{e['rank']}.")
        lines.append(f"{medal} {e['name']} – Lvl {e['level']} ({e['xp']} XP)")
    rank = db.get_rank(update.effective_user.id)
    if rank:
        lines.append(f"\n📍 Your rank: #{rank}")
    lines.append("\n_ - made with love by Sparsh Singhal _")
    await reply(update, "\n".join(lines))


async def upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    uid = user.id if user else 0
    await reply(update,
        f"💎 *Unlock StudyGenie Pro – ₹{config.PRO_PRICE_INR}/30 days*\n\n"
        "All 28 Pro features unlocked:\n"
        "• Unlimited doubts\n• Savage Roast • NCERT • Mind Maps\n"
        "• Diagrams • Derivations • Numerical Solver\n"
        "• MCQ + Mock Tests • Essay/Resume\n"
        "• Image OCR • Career Guide • Sparsh Tips\n"
        "• 2× XP + Priority\n\n"
        f"Pay here: https://{config.VERCEL_URL}/pay?uid={uid}\n\n"
        "_ - made with love by Sparsh Singhal _"
    )


async def about_sparsh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reply(update,
        "👨‍💻 *About Sparsh Singhal*\n\n"
        "Creator of StudyGenie – India's most fun gamified AI tutor.\n\n"
        "Built with ❤️ for every Indian student – from Class 6 to competitive exams.\n\n"
        "_ - made with love by Sparsh Singhal _"
    )


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query: return
    await query.answer()
    data = query.data or ""
    user = update.effective_user
    uid = user.id if user else 0
    is_pro = db.is_pro(uid)

    if data == "menu_main":
        await menu(update, context)
    elif data == "menu_ask":
        await reply(update, "📚 *Ask anything!*\n\nJust type your question now.\n\n_ - made with love by Sparsh Singhal _")
    elif data == "menu_tools":
        await reply(update, "🛠 *Choose a Tool:*", tools_menu(is_pro))
    elif data == "menu_progress":
        await progress(update, context)
    elif data == "menu_lb":
        await leaderboard(update, context)
    elif data == "menu_streak":
        await streak_cmd(update, context)
    elif data == "menu_upgrade":
        await upgrade(update, context)
    elif data == "menu_about":
        await about_sparsh(update, context)
    elif data == "menu_prostatus":
        await reply(update, "👑 You are already a *PRO* member!\n\nEnjoy unlimited power.\n\n_ - made with love by Sparsh Singhal _")
    elif data.startswith("tool_"):
        tool = data.replace("tool_", "")
        db.set_tool(uid, tool)
        await reply(update, f"✅ Tool selected: *{tool.title()}*\n\nAb apna sawaal type karo.\n\n_ - made with love by Sparsh Singhal _")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.message or not update.message.photo:
        return
    uid = user.id
    is_pro = db.is_pro(uid)
    if not is_pro:
        await reply(update, f"📷 Image Doubt Scan is *Pro-only*.\n\nUpgrade for ₹{config.PRO_PRICE_INR}/30 days.\n\n_ - made with love by Sparsh Singhal _",
                    InlineKeyboardMarkup([[InlineKeyboardButton(f"💎 Upgrade ₹{config.PRO_PRICE_INR}", callback_data="menu_upgrade")]]))
        return

    await typing(update)
    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        img_bytes = bytes(await file.download_as_bytearray())
        caption = (update.message.caption or "").strip()
        start = time.time()
        answer = run_ai(ai.answer_with_image, img_bytes, "image/jpeg", caption, "ocr", True)
        elapsed = time.time() - start
        if not answer:
            await reply(update, "😔 Could not read the image. Try a clearer photo.")
            return
        udata = db.ensure_user(uid, user.username or "", user.full_name or "Student")
        xp_gain = config.XP_QUESTION * 2
        xp, level = db.add_xp(uid, xp_gain)
        questions = int(udata.get("questions_asked", 0)) + 1
        udata["questions_asked"] = str(questions)
        db.save_user(uid, udata)
        footer = f"\n\n━━━━━━━━━━━━━━━\n📷 OCR | ⚡ {elapsed:.1f}s | ⭐ +{xp_gain} XP (2× Pro) | Level {level}\n_ - made with love by Sparsh Singhal _"
        full = answer + footer
        if len(full) <= 4096:
            await reply(update, full)
        else:
            for i, chunk in enumerate([full[i:i+4000] for i in range(0, len(full), 4000)]):
                if i == 0:
                    await reply(update, chunk)
                elif update.message:
                    await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.exception("Photo handler: %s", e)
        await reply(update, "😔 Error processing image. Please try again.")


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
            .defaults(Defaults(parse_mode=ParseMode.MARKDOWN))
            .build()
        )
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("menu", menu))
        app.add_handler(CommandHandler("ask", cmd_ask))
        app.add_handler(CommandHandler("progress", progress))
        app.add_handler(CommandHandler("streak", streak_cmd))
        app.add_handler(CommandHandler("leaderboard", leaderboard))
        app.add_handler(CommandHandler("upgrade", upgrade))
        app.add_handler(CommandHandler("about", about_sparsh))
        app.add_handler(CallbackQueryHandler(callback))
        app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
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
    try:
        return send_from_directory(".", "sparsh.jpg")
    except Exception:
        return "", 404


# NOTE: FRONTEND_HTML is very long. Keep your original beautiful frontend.
# Only the AI backend has been upgraded. For the complete file with full HTML,
# you can keep your existing FRONTEND_HTML string exactly as it was.

@app.route("/")
def home():
    return render_template_string(
        """<!DOCTYPE html><html><head><title>StudyGenie by Sparsh Singhal</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>body{font-family:system-ui;background:#0b1220;color:#f1f5f9;text-align:center;padding:2rem}
        a{color:#22d3ee}</style></head><body>
        <h1>🎓 StudyGenie by Sparsh Singhal</h1>
        <p>All exams support • Groq + Gemini dual AI</p>
        <p><a href="/api/debug/ai">Test AI Status</a></p>
        <p>Made with ❤️ by Sparsh Singhal</p>
        </body></html>""",
        price=config.PRO_PRICE_INR,
        free_daily=config.FREE_DAILY,
        free_lifetime=config.FREE_LIFETIME,
    )


@app.route("/health")
def health():
    redis_ok = False
    if db.redis:
        try:
            redis_ok = bool(db.redis.ping())
        except Exception:
            pass
    return jsonify({
        "ok": True,
        "redis": redis_ok,
        "groq": ai.groq_client is not None,
        "gemini": ai.gemini_client is not None,
        "primary": config.AI_PRIMARY,
        "version": "StudyGenie by Sparsh Singhal v3.0 (All Exams + Dual AI)",
        "creator": "Sparsh Singhal",
    })


@app.route("/api/debug/ai")
def debug_ai():
    results = {
        "primary": config.AI_PRIMARY,
        "groq_key_present": bool(config.GROQ_API_KEY),
        "gemini_key_present": bool(config.GOOGLE_API_KEY),
    }

    # ---------- Test Groq ----------
    if ai.groq_client:
        t0 = time.time()
        try:
            resp = ai.groq_client.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=[{"role": "user", "content": "Reply with exactly: OK StudyGenie"}],
                max_tokens=20,
                temperature=0,
                timeout=20,
            )
            text = (resp.choices[0].message.content or "").strip()
            results["groq"] = {
                "ok": bool(text),
                "model": config.GROQ_MODEL,
                "reply": text[:150],
                "elapsed": round(time.time() - t0, 2),
            }
        except Exception as e:
            results["groq"] = {
                "ok": False,
                "model": config.GROQ_MODEL,
                "error": str(e),
                "elapsed": round(time.time() - t0, 2),
            }
    else:
        results["groq"] = {"ok": False, "error": "Groq client not initialized (check GROQ_API_KEY)"}

    # ---------- Test Gemini ----------
    if ai.gemini_client:
        t0 = time.time()
        try:
            resp = ai.gemini_client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=["Reply with exactly: OK StudyGenie"],
                config=genai_types.GenerateContentConfig(
                    temperature=0,
                    max_output_tokens=20,
                ),
            )
            text = (resp.text or "").strip()
            results["gemini"] = {
                "ok": bool(text),
                "model": config.GEMINI_MODEL,
                "reply": text[:150],
                "elapsed": round(time.time() - t0, 2),
            }
        except Exception as e:
            results["gemini"] = {
                "ok": False,
                "model": config.GEMINI_MODEL,
                "error": str(e),
                "elapsed": round(time.time() - t0, 2),
            }
    else:
        results["gemini"] = {"ok": False, "error": "Gemini client not initialized (check GOOGLE_API_KEY)"}

    return jsonify(results)


@app.route("/api/webask", methods=["POST"])
def web_ask():
    data = request.get_json(silent=True) or {}
    q = (data.get("question") or "").strip()
    tool = (data.get("tool") or "general").strip().lower()
    client_id = (data.get("client_id") or request.remote_addr or "anon").strip()
    image_b64 = data.get("image_base64") or ""

    if is_rate_limited(f"web:{client_id}", max_calls=10, window_sec=60):
        return jsonify({"answer": "Too many requests. Please wait a minute.\n\n- made with love by Sparsh Singhal"}), 429

    if not q and not image_b64:
        return jsonify({"answer": "Please type a question or upload an image"}), 400

    uid = f"web:{client_id}"
    udata = db.ensure_user(uid, full_name="Web Student", platform="web")
    is_pro = db.is_pro(uid)

    pro_only = {"roast", "ncert", "mindmap", "important", "diagram", "derivation", "numerical", "mcq", "essay", "resume", "youtube", "career", "voice", "ocr", "mock", "tips"}
    if (tool in pro_only or image_b64) and not is_pro:
        return jsonify({"answer": f"🔒 This feature is Pro-only.\n\nUpgrade for ₹{config.PRO_PRICE_INR}/30 days.\n\n- made with love by Sparsh Singhal"})

    if not is_pro:
        can, quota = db.check_quota(uid)
        if not can:
            return jsonify({"answer": f"❌ Quota finished!\n\nUpgrade to Pro.\n\n- made with love by Sparsh Singhal", "quota": quota})

    start = time.time()
    if image_b64:
        try:
            import base64 as b64mod
            img_bytes = b64mod.b64decode(image_b64)
            answer = run_ai(ai.answer_with_image, img_bytes, data.get("image_mime", "image/jpeg"), q, "ocr", is_pro)
        except Exception as e:
            logger.error("Image error: %s", e)
            answer = "Could not read the image."
    else:
        answer = run_ai(ai.answer, q, tool, is_pro=is_pro)
    elapsed = time.time() - start

    if not answer or str(answer).startswith("ERROR:"):
        return jsonify({"answer": "😔 Couldn't generate answer. Please try again.\n\n- made with love by Sparsh Singhal"})

    if not is_pro:
        db.consume_quota(uid)

    xp_gain = config.XP_QUESTION * (2 if is_pro else 1)
    xp, level = db.add_xp(uid, xp_gain)
    questions = int(udata.get("questions_asked", 0)) + 1
    udata["questions_asked"] = str(questions)
    db.save_user(uid, udata)

    _, quota = db.check_quota(uid)
    rank = db.get_rank(uid)
    footer = f"\n\n━━━━━━━━━━━━━━━\n⚡ {elapsed:.1f}s | ⭐ +{xp_gain} XP{' (2× Pro)' if is_pro else ''} | Level {level}\n- made with love by Sparsh Singhal"
    return jsonify({"answer": answer + footer, "xp": xp, "level": level, "rank": rank, "quota": quota, "elapsed": round(elapsed, 2)})


@app.route("/api/leaderboard")
def api_leaderboard():
    return jsonify({"board": db.get_leaderboard(15), "live": True})


@app.route("/api/dev/stats")
def dev_stats():
    code = request.args.get("code", "")
    if code != config.DEV_SECRET:
        return jsonify({"ok": False}), 403
    return jsonify({"ok": True, **db.get_stats()})


@app.route("/api/razorpay/webhook", methods=["POST"])
def razorpay_webhook():
    try:
        body = request.get_data()
        received_sig = request.headers.get("X-Razorpay-Signature", "")
        if config.RAZORPAY_WEBHOOK_SECRET:
            expected = hmac.new(config.RAZORPAY_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, received_sig):
                return jsonify({"ok": False}), 400
        payload = request.get_json(force=True)
        if payload.get("event") == "payment.captured":
            entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
            payment_id = entity.get("id", "")
            notes = entity.get("notes", {}) or {}
            uid = notes.get("user_id", "")
            if payment_id and not db.mark_payment_processed(payment_id):
                return jsonify({"ok": True, "duplicate": True})
            if uid:
                db.activate_pro(uid, days=30)
                db.add_badge(uid, "Pro Warrior 👑")
                logger.info("Pro activated for %s", uid)
        return jsonify({"ok": True})
    except Exception as e:
        logger.error("Razorpay webhook: %s", e)
        return jsonify({"ok": False}), 500


@app.route("/api/whatsapp", methods=["GET", "POST"])
def whatsapp_webhook():
    if request.method == "GET":
        if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == config.WHATSAPP_VERIFY_TOKEN:
            return request.args.get("hub.challenge"), 200
        return "Forbidden", 403
    try:
        data = request.get_json(force=True, silent=True) or {}
        for ent in data.get("entry", []):
            for change in ent.get("changes", []):
                value = change.get("value", {})
                contacts = value.get("contacts", [])
                profile_name = contacts[0].get("profile", {}).get("name", "") if contacts else ""
                for msg in value.get("messages", []):
                    if msg.get("type") == "text":
                        from_number = msg.get("from")
                        text = msg.get("text", {}).get("body", "").strip()
                        if from_number and text:
                            process_whatsapp_message(from_number, text, profile_name)
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("WhatsApp webhook: %s", e)
        return jsonify({"ok": False}), 500


@app.route("/api/webhook", methods=["POST"])
def telegram_webhook():
    if config.WEBHOOK_SECRET and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != config.WEBHOOK_SECRET:
        return jsonify({"ok": False}), 401
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"ok": False}), 400
        uid = str(data.get("message", {}).get("from", {}).get("id") or data.get("callback_query", {}).get("from", {}).get("id") or "tg")
        if is_rate_limited(f"tg:{uid}", max_calls=20, window_sec=60):
            return jsonify({"ok": True})

        async def _run():
            application = await get_app()
            update = Update.de_json(data, application.bot)
            if update:
                await application.process_update(update)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(_run())
            else:
                loop.run_until_complete(_run())
        except RuntimeError:
            asyncio.run(_run())
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("Telegram webhook: %s", e)
        return jsonify({"ok": False}), 500


@app.route("/api/setup")
def setup():
    if not config.VERCEL_URL or not config.BOT_TOKEN:
        return jsonify({"error": "Missing VERCEL_URL or BOT_TOKEN"}), 400
    webhook_url = f"https://{config.VERCEL_URL.rstrip('/')}/api/webhook"
    api = f"https://api.telegram.org/bot{config.BOT_TOKEN}/setWebhook"
    payload = {"url": webhook_url}
    if config.WEBHOOK_SECRET:
        payload["secret_token"] = config.WEBHOOK_SECRET
    try:
        r = requests.post(api, json=payload, timeout=20)
        data = r.json() if r.content else {}
        return jsonify({"ok": data.get("ok"), "telegram_webhook": webhook_url, "response": data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
