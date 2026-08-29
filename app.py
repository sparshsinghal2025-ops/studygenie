"""
StudyGenie by Sparsh Singhal
Fully Gamified Multi-Platform E-Learning Bot
Telegram + WhatsApp + Web Dashboard
Production-ready (thousands scale) for Railway / Render / Fly / VPS
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

        self.GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()
        self.GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

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
        if not self.GOOGLE_API_KEY:
            logger.error("GOOGLE_API_KEY is missing")


config = Config()

# ============================================================================
# THOUSANDS-READY INFRA
# Redis rate limit • connection pool • AI thread pool • idempotency
# ============================================================================

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

# Shared AI executor – keeps Flask/Gunicorn workers from blocking on Gemini
_AI_POOL = ThreadPoolExecutor(max_workers=int(os.getenv("AI_POOL_WORKERS", "8")), thread_name_prefix="ai")
_AI_TIMEOUT = float(os.getenv("AI_TIMEOUT_SEC", "55"))

# Fallback in-memory rate limit only if Redis is down
_rate_lock = Lock()
_rate_buckets: dict[str, list[float]] = defaultdict(list)


_redis_for_rl: Optional[redis.Redis] = None  # set after Database() init


def is_rate_limited(key: str, max_calls: int = 12, window_sec: int = 60) -> bool:
    """
    Distributed sliding-window rate limit via Redis.
    Falls back to process-local memory if Redis is unavailable.
    Returns True if the key has exceeded the limit.
    """
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

    # Local fallback
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
    """Run AI work in the shared thread pool with a hard timeout."""
    fut = _AI_POOL.submit(fn, *args, **kwargs)
    try:
        return fut.result(timeout=_AI_TIMEOUT)
    except FuturesTimeout:
        logger.error("AI call timed out after %ss", _AI_TIMEOUT)
        return None
    except Exception as e:
        logger.error("AI pool error: %s", e)
        return None


# ============================================================================
# DATABASE (pooled Redis – thousands-ready)
# ============================================================================


class Database:
    def __init__(self) -> None:
        self.redis = self._connect()

    def _connect(self) -> Optional[redis.Redis]:
        if not config.REDIS_URL:
            logger.warning("No Redis – limited mode (single-instance only)")
            return None
        try:
            # Connection pool tuned for multi-worker Gunicorn (thousands of users)
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
            logger.info("Redis OK (pooled, max_conn=%s)", pool.max_connections)
            return r
        except Exception as e:
            logger.error("Redis fail: %s", e)
            return None

    # ----- multi-instance tool selection (Telegram) -----
    def set_tool(self, uid: str | int, tool: str, ttl: int = 300) -> None:
        if not self.redis:
            return
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

    # ----- Razorpay payment idempotency -----
    def mark_payment_processed(self, payment_id: str) -> bool:
        """Return True if this payment was NOT seen before (first time)."""
        if not self.redis or not payment_id:
            return True
        try:
            # SET NX – only succeeds the first time
            return bool(self.redis.set(f"pay:done:{payment_id}", "1", nx=True, ex=86400 * 90))
        except Exception:
            return True

    def is_payment_processed(self, payment_id: str) -> bool:
        if not self.redis or not payment_id:
            return False
        try:
            return bool(self.redis.exists(f"pay:done:{payment_id}"))
        except Exception:
            return False

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

    def ensure_user(
        self,
        uid: str | int,
        username: str = "",
        full_name: str = "",
        platform: str = "telegram",
    ) -> Dict[str, str]:
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
        user.update(
            {
                "streak": str(new),
                "best_streak": str(best),
                "shields": str(shields),
                "last_activity": today,
            }
        )
        self.save_user(uid, user)
        return {"current": new, "best": best, "shields": shields}

    def check_quota(self, uid: str | int) -> Tuple[bool, Dict[str, int]]:
        if self.is_pro(uid):
            return True, {"daily_left": -1, "lifetime_left": -1}
        if not self.redis:
            return True, {
                "daily_left": config.FREE_DAILY,
                "lifetime_left": config.FREE_LIFETIME,
            }
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
            return True, {
                "daily_left": config.FREE_DAILY,
                "lifetime_left": config.FREE_LIFETIME,
            }

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
                out.append(
                    {
                        "rank": rank,
                        "name": (u or {}).get("full_name", "Student")[:20],
                        "xp": int(xp),
                        "level": int((u or {}).get("level", 1)),
                        "platform": (u or {}).get("platform", "web"),
                    }
                )
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
            "Solve 1 PYQ",
            "Make short notes on any topic",
        ]
        quest = secrets.choice(quests)
        user = self.get_user(uid) or {}
        user["daily_quest"] = quest
        user["quest_progress"] = "0"
        self.save_user(uid, user)
        return quest

    def get_stats(self) -> Dict[str, int]:
        if not self.redis:
            return {"total_users": 0, "total_questions": 0, "online_approx": 0}
        try:
            total_users = self.redis.scard("stats:users") or 0
            total_q = int(self.redis.get("stats:total_questions") or 0)
            lb_size = self.redis.zcard("leaderboard") or 0
            return {
                "total_users": int(total_users),
                "total_questions": total_q,
                "online_approx": int(lb_size),
            }
        except Exception:
            return {"total_users": 0, "total_questions": 0, "online_approx": 0}


db = Database()
_redis_for_rl = db.redis  # for distributed rate limiting

# ============================================================================
# AI SERVICE (with simple retry)
# ============================================================================


class AIService:
    def __init__(self) -> None:
        self.client = None
        if config.GOOGLE_API_KEY:
            try:
                self.client = genai.Client(api_key=config.GOOGLE_API_KEY)
            except Exception as e:
                logger.error("Gemini init: %s", e)

    def _base_prompt(self, is_pro: bool) -> str:
        base = (
            "You are StudyGenie by Sparsh Singhal – India's most fun gamified AI tutor "
            "for JEE/NEET/GATE/Boards. Created with ❤️ by Sparsh Singhal. "
            "Reply in natural Hinglish. Be encouraging, use emojis, explain step-by-step. "
            "Keep answers clear and exam-oriented.\n\n"
        )
        if is_pro:
            base += (
                "User is PRO – give deeper explanations, extra tips, memory tricks, "
                "exam strategy, common mistakes, and one bonus question when useful.\n\n"
            )
        return base

    def _templates(self, base: str, question: str) -> Dict[str, str]:
        return {
            "general": f"{base}Question:\n{question}",
            "explain": f"{base}Explain simply with examples + analogy + real-life connection.\n\n{question}",
            "solve": f"{base}Solve step-by-step with full working, units, and final boxed answer.\n\n{question}",
            "notes": f"{base}Create short exam-ready chapter notes + key formulas + one-liners.\n\n{question}",
            "pyq": f"{base}Solve this Previous Year Question carefully. Show full working, mark concept used, and give similar PYQ tip.\n\n{question}",
            "formula": f"{base}List all important formulas with short notes, units, and when to use them.\n\n{question}",
            "planner": f"{base}Create a realistic 7-day study plan with daily targets, revision slots, and mock tests.\n\nTopic/Goal: {question}",
            "mock": f"{base}Generate 5 high-quality MCQs (JEE/NEET level) with options, correct answer, and detailed explanation.\n\nTopic: {question}",
            "roast": f"{base}Hinglish Savage Roast Mode (still educational). Roast the student's doubt or common mistakes in a fun, motivational way while teaching the correct concept.\n\nDoubt: {question}",
            "ncert": f"{base}Give complete NCERT-style explanation + in-text + exercise style answers for this topic/question. Keep it board + JEE/NEET friendly.\n\n{question}",
            "mindmap": f"{base}Create a clear hierarchical mind-map in pure text (use indentation, arrows, and bullets). Cover main topic → subtopics → key points → formulas.\n\nTopic: {question}",
            "important": f"{base}Generate Important Questions Bank (10-12 high-yield questions) for this chapter/topic with short answers or hints.\n\nTopic: {question}",
            "diagram": f"{base}Explain the diagram / figure in detail. Describe what each part shows, labelled parts meaning, and exam-relevant points.\n\n{question}",
            "derivation": f"{base}Give full derivation / proof step-by-step with reasoning at each step. Mention assumptions and final result clearly.\n\n{question}",
            "numerical": f"{base}Numerical Solver: Solve with complete steps, formula used, substitution, calculation, units, and significant figures. Highlight final answer.\n\n{question}",
            "mcq": f"{base}MCQ Quiz Generator: Create 8 high-quality MCQs with 4 options each, mark correct answer, and give short explanation. Mix easy-medium-hard.\n\nTopic: {question}",
            "essay": f"{base}Write a well-structured essay / letter / application / formal writing as requested. Use proper format, good vocabulary, and exam-suitable length.\n\nRequest: {question}",
            "resume": f"{base}Create a clean, modern resume / CV content (or improve the given one) for a student. Use sections: Objective, Education, Skills, Projects, Achievements. Keep it ATS-friendly.\n\nDetails: {question}",
            "youtube": f"{base}YouTube Video Summarizer style: Give a structured summary, key timestamps-style points, important formulas/concepts, and 5 revision questions as if summarizing a study video on this topic.\n\nTopic/Video: {question}",
            "career": f"{base}Give practical career guidance for Indian students (JEE/NEET/Boards path). Include options, required skills, future scope, and realistic advice.\n\nQuery: {question}",
            "tips": f"{base}Founder Sparsh Singhal Direct Tips mode: Give sharp, no-nonsense study tips, CODE (Concept-Oriented Daily Effort) + DRY RUN strategy, exam psychology, and motivation. Speak as the creator.\n\nTopic: {question}",
            "voice": f"{base}(Voice-mode simulation) Give a short, spoken-style answer that is easy to read aloud. Keep sentences natural and conversational.\n\n{question}",
            "ocr": f"{base}Image Doubt / OCR mode: Read the question from the image carefully (OCR). Then solve it completely step-by-step.\n\nExtra text from user: {question}",
        }

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

        base = self._base_prompt(is_pro)
        templates = self._templates(base, question)
        prompt = templates.get(tool, templates["general"])

        for attempt in range(2):
            try:
                resp = self.client.models.generate_content(
                    model=config.GEMINI_MODEL,
                    contents=[prompt],
                    config=genai_types.GenerateContentConfig(
                        temperature=0.35,
                        max_output_tokens=2800 if is_pro else 1600,
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
                logger.error("Gemini attempt %s: %s", attempt + 1, e)
                if attempt == 0:
                    time.sleep(0.7)
                    continue
                return None
        return None

    def answer_with_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        question: str = "",
        tool: str = "ocr",
        is_pro: bool = False,
    ) -> Optional[str]:
        """True Gemini Vision OCR + solve for image doubts (Pro feature)."""
        if not self.client:
            return "AI temporarily unavailable. Try again soon."
        if not is_pro:
            return (
                "📷 Image Doubt Scan is a *Pro-only* feature.\n\n"
                f"Upgrade for ₹{config.PRO_PRICE_INR}/30 days to unlock OCR + all 28 Pro tools.\n\n"
                "- made with love by Sparsh Singhal"
            )

        base = self._base_prompt(is_pro)
        extra = question.strip() or "Solve the question shown in the image completely."
        prompt = (
            f"{base}"
            "You can SEE the image. First do accurate OCR of any handwritten or printed text. "
            "Then solve the question step-by-step with full working. "
            "If it is a diagram, explain every labelled part and the concept.\n\n"
            f"User note: {extra}"
        )

        try:
            import base64 as b64mod
            # google-genai accepts Part with inline data
            part = genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            resp = self.client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=[part, prompt],
                config=genai_types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=3000,
                ),
            )
            return (resp.text or "").strip() or None
        except Exception as e:
            logger.error("Gemini vision error: %s", e)
            # Fallback: try pure text if vision fails
            return self.answer(
                f"[Image OCR failed, user said]: {extra}",
                tool="ocr",
                is_pro=is_pro,
            )


ai = AIService()

# ============================================================================
# WHATSAPP HELPER
# ============================================================================


def send_whatsapp_message(to: str, text: str) -> bool:
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
        "text": {"body": text[:4096]},
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
    uid = from_number

    # Rate limit
    if is_rate_limited(f"wa:{uid}", max_calls=15, window_sec=60):
        send_whatsapp_message(
            from_number,
            "Too many messages. Please wait a minute.\n\n_ - made with love by Sparsh Singhal _",
        )
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
            f"India's most fun gamified AI tutor for JEE • NEET • GATE • Boards.\n\n"
            f"⭐ Level {udata.get('level', 1)} | XP {udata.get('xp', 0)}\n"
            f"🔥 Streak: {streak['current']} days\n\n"
        )
        if not is_pro:
            msg += (
                f"🆓 Free plan: *{quota['daily_left']}* questions left today "
                f"| *{quota['lifetime_left']}* lifetime left\n"
                f"(Daily limit: {config.FREE_DAILY} | Lifetime: {config.FREE_LIFETIME})\n\n"
            )
        msg += (
            "Just type any question and I will answer instantly!\n\n"
            "_ - made with love by Sparsh Singhal _"
        )
        send_whatsapp_message(from_number, msg)
        return

    if lower.startswith("/upgrade") or "upgrade" in lower or "pro" in lower:
        msg = (
            f"💎 *Unlock Pro – ₹{config.PRO_PRICE_INR} for 30 days*\n\n"
            "*All 28 Pro Features:*\n"
            "Unlimited doubts • Savage Roast • NCERT • PYQ • Notes • Mind Maps\n"
            "Formulas • Important Qs • Leaderboard • XP+Shield • Sounds\n"
            "Diagram • Derivation • Numerical Solver • MCQ Quiz • Mock Test\n"
            "Essay/Letter • Resume Builder • Voice style • Image/OCR\n"
            "YT Summarizer • Career Guide • No Ads • Priority • Daily Missions\n"
            "Unlimited Ammo • Plan Tracking • Sparsh Tips + CODE+DRY RUN\n\n"
            f"Pay here: https://{config.VERCEL_URL}/pay?uid={uid}\n\n"
            "Pro activates automatically after payment.\n\n"
            "_ - made with love by Sparsh Singhal _"
        )
        send_whatsapp_message(from_number, msg)
        return

    if not is_pro:
        can, quota = db.check_quota(uid)
        if not can:
            send_whatsapp_message(
                from_number,
                "❌ Daily / lifetime quota finished!\n\n"
                f"Free plan: {config.FREE_DAILY}/day & {config.FREE_LIFETIME} lifetime.\n"
                f"Upgrade to Pro for unlimited access: https://{config.VERCEL_URL}/pay?uid={uid}\n\n"
                "_ - made with love by Sparsh Singhal _",
            )
            return

    if lower.startswith(("explain", "what is", "why", "how")):
        tool = "explain"
    elif lower.startswith(("solve", "calculate", "find")):
        tool = "solve"
    elif lower.startswith(("notes", "summarize")):
        tool = "notes"
    elif lower.startswith(("plan", "schedule")):
        tool = "planner"
    elif lower.startswith(("roast", "savage")):
        tool = "roast"
    elif lower.startswith(("mindmap", "mind map")):
        tool = "mindmap"
    elif lower.startswith(("derivation", "derive", "proof")):
        tool = "derivation"
    elif lower.startswith(("numerical",)):
        tool = "numerical"
    elif lower.startswith(("mcq", "quiz")):
        tool = "mcq"
    elif lower.startswith(("essay", "letter", "application")):
        tool = "essay"
    elif lower.startswith(("resume", "cv")):
        tool = "resume"
    elif lower.startswith(("career",)):
        tool = "career"
    elif lower.startswith(("tips", "sparsh")):
        tool = "tips"
    elif lower.startswith(("ncert",)):
        tool = "ncert"
    else:
        tool = "general"

    # Gate pro-only tools on WhatsApp too
    pro_only = {
        "roast", "ncert", "mindmap", "important", "diagram", "derivation",
        "numerical", "mcq", "essay", "resume", "youtube", "career",
        "voice", "ocr", "mock", "tips",
    }
    if tool in pro_only and not is_pro:
        send_whatsapp_message(
            from_number,
            f"🔒 *{tool.title()}* is a Pro-only feature.\n\n"
            f"Upgrade for ₹{config.PRO_PRICE_INR}/30 days: https://{config.VERCEL_URL}/pay?uid={uid}\n\n"
            "_ - made with love by Sparsh Singhal _",
        )
        return

    start = time.time()
    answer = run_ai(ai.answer, text, tool, is_pro=is_pro)
    elapsed = time.time() - start

    if not answer:
        send_whatsapp_message(
            from_number,
            "😔 Couldn't generate answer right now. Please try again.\n\n_ - made with love by Sparsh Singhal _",
        )
        return

    if not is_pro:
        db.consume_quota(uid)

    xp_gain = config.XP_QUESTION * (2 if is_pro else 1)
    xp, level = db.add_xp(uid, xp_gain)
    questions = int(udata.get("questions_asked", 0)) + 1
    udata["questions_asked"] = str(questions)
    db.save_user(uid, udata)

    if questions == 1:
        db.add_badge(uid, "First Step 🐣")
    if questions >= 50:
        db.add_badge(uid, "Knowledge Seeker 📚")
    if level >= 5:
        db.add_badge(uid, "Rising Star ⭐")
    if questions >= 100:
        db.add_badge(uid, "Century Club 💯")

    footer = (
        f"\n\n━━━━━━━━━━━━━━━\n"
        f"⚡ {elapsed:.1f}s | ⭐ +{xp_gain} XP{' (2× Pro)' if is_pro else ''} | Level {level}\n"
        f"_ - made with love by Sparsh Singhal _"
    )
    full = answer + footer
    if len(full) <= 4000:
        send_whatsapp_message(from_number, full)
    else:
        for i in range(0, len(full), 3900):
            send_whatsapp_message(from_number, full[i : i + 3900])


# ============================================================================
# TELEGRAM KEYBOARDS & HELPERS
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
        rows.append(
            [InlineKeyboardButton(f"💎 Upgrade to Pro – ₹{config.PRO_PRICE_INR}/mo", callback_data="menu_upgrade")]
        )
    else:
        rows.append([InlineKeyboardButton("👑 Pro Active", callback_data="menu_prostatus")])
    rows.append([InlineKeyboardButton("👨‍💻 About Sparsh Singhal", callback_data="menu_about")])
    return InlineKeyboardMarkup(rows)


def tools_menu(is_pro: bool) -> InlineKeyboardMarkup:
    # Free tools (available to everyone)
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
        # Full Pro toolbox (covers majority of the 28 Pro features)
        rows.extend(
            [
                [
                    InlineKeyboardButton("🔥 Savage Roast", callback_data="tool_roast"),
                    InlineKeyboardButton("📖 NCERT Mode", callback_data="tool_ncert"),
                ],
                [
                    InlineKeyboardButton("🧠 Mind Map", callback_data="tool_mindmap"),
                    InlineKeyboardButton("⭐ Important Qs", callback_data="tool_important"),
                ],
                [
                    InlineKeyboardButton("🖼 Diagram", callback_data="tool_diagram"),
                    InlineKeyboardButton("📐 Derivation", callback_data="tool_derivation"),
                ],
                [
                    InlineKeyboardButton("🔢 Numerical", callback_data="tool_numerical"),
                    InlineKeyboardButton("🧪 MCQ Quiz", callback_data="tool_mcq"),
                ],
                [
                    InlineKeyboardButton("📝 Essay/Letter", callback_data="tool_essay"),
                    InlineKeyboardButton("📄 Resume", callback_data="tool_resume"),
                ],
                [
                    InlineKeyboardButton("🎬 YT Summary", callback_data="tool_youtube"),
                    InlineKeyboardButton("🎯 Career Guide", callback_data="tool_career"),
                ],
                [
                    InlineKeyboardButton("🎤 Voice Style", callback_data="tool_voice"),
                    InlineKeyboardButton("📷 Image/OCR", callback_data="tool_ocr"),
                ],
                [
                    InlineKeyboardButton("🧪 Mock Test", callback_data="tool_mock"),
                    InlineKeyboardButton("💡 Sparsh Tips", callback_data="tool_tips"),
                ],
            ]
        )
    else:
        rows.append(
            [InlineKeyboardButton("🔒 Unlock 20+ Pro Tools", callback_data="menu_upgrade")]
        )
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


async def process_question(
    update: Update, context: ContextTypes.DEFAULT_TYPE, q: str, tool: str = "general"
) -> None:
    user = update.effective_user
    if not user:
        return
    uid = user.id
    udata = db.ensure_user(
        uid, user.username or "", user.full_name or "Student", platform="telegram"
    )
    is_pro = db.is_pro(uid)

    # Gate Pro-only tools
    pro_only = {
        "roast", "ncert", "mindmap", "important", "diagram", "derivation",
        "numerical", "mcq", "essay", "resume", "youtube", "career",
        "voice", "ocr", "mock", "tips",
    }
    if tool in pro_only and not is_pro:
        await reply(
            update,
            f"🔒 *{tool.title()}* is Pro-only.\n\n"
            f"Upgrade for ₹{config.PRO_PRICE_INR}/30 days to unlock all 28 features.\n\n"
            "_ - made with love by Sparsh Singhal _",
            InlineKeyboardMarkup(
                [[InlineKeyboardButton(f"💎 Upgrade ₹{config.PRO_PRICE_INR}", callback_data="menu_upgrade")]]
            ),
        )
        return

    if not is_pro:
        can, quota = db.check_quota(uid)
        if not can:
            await reply(
                update,
                "❌ *Quota finished!*\n\n"
                f"Free: {config.FREE_DAILY}/day & {config.FREE_LIFETIME} lifetime.\n"
                "Upgrade to Pro for unlimited access + exclusive tools.\n\n"
                "_ - made with love by Sparsh Singhal _",
                InlineKeyboardMarkup(
                    [[InlineKeyboardButton(f"💎 Upgrade ₹{config.PRO_PRICE_INR}", callback_data="menu_upgrade")]]
                ),
            )
            return

    await typing(update)
    start = time.time()
    answer = run_ai(ai.answer, q, tool, is_pro=is_pro)
    elapsed = time.time() - start

    if not answer:
        await reply(
            update,
            "😔 Couldn't generate answer. Please try again.\n\n_ - made with love by Sparsh Singhal _",
        )
        return

    if not is_pro:
        db.consume_quota(uid)

    # Pro users get 2× XP
    xp_gain = config.XP_QUESTION * (2 if is_pro else 1)
    xp, level = db.add_xp(uid, xp_gain)
    questions = int(udata.get("questions_asked", 0)) + 1
    udata["questions_asked"] = str(questions)
    db.save_user(uid, udata)

    if questions == 1:
        db.add_badge(uid, "First Step 🐣")
    if questions >= 50:
        db.add_badge(uid, "Knowledge Seeker 📚")
    if level >= 5:
        db.add_badge(uid, "Rising Star ⭐")
    if questions >= 100:
        db.add_badge(uid, "Century Club 💯")

    footer = (
        f"\n\n━━━━━━━━━━━━━━━\n"
        f"⚡ {elapsed:.1f}s | ⭐ +{xp_gain} XP{' (2× Pro)' if is_pro else ''} | Level {level}\n"
        f"_ - made with love by Sparsh Singhal _"
    )
    full = answer + footer
    if len(full) <= 4096:
        await reply(update, full)
    else:
        for i, chunk in enumerate([full[i : i + 4000] for i in range(0, len(full), 4000)]):
            if i == 0:
                await reply(update, chunk)
            else:
                if update.message:
                    await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    db.ensure_user(user.id, user.username or "", user.full_name or "Student")
    is_pro = db.is_pro(user.id)
    _, quota = db.check_quota(user.id)
    text = (
        f"🎓 *Welcome to StudyGenie by Sparsh Singhal*, {user.first_name or 'Champion'}!\n\n"
        "India's most fun *gamified* AI tutor for JEE • NEET • GATE • Boards.\n\n"
        "Also available on *WhatsApp* & Web!\n\n"
    )
    if not is_pro:
        text += (
            f"🆓 Free: *{quota['daily_left']}* left today | *{quota['lifetime_left']}* lifetime\n"
            f"(Daily {config.FREE_DAILY} • Lifetime {config.FREE_LIFETIME})\n\n"
        )
    text += "Created with ❤️ by *Sparsh Singhal*\n\nJust type any question or open the menu 👇"
    await reply(update, text, main_menu(is_pro))


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
        text += f"\n❓ Questions left today: {quota['daily_left']} | Lifetime: {quota['lifetime_left']}\n"
    text += "\n*Choose:*\n\n_ - made with love by Sparsh Singhal _"
    await reply(update, text, main_menu(is_pro))


async def free_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    lower = text.lower()

    # Prefer tool previously selected from menu (Redis = multi-worker safe)
    selected = db.pop_tool(update.effective_user.id) if update.effective_user else None
    if not selected and context.user_data:
        selected = context.user_data.pop("selected_tool", None)

    if selected:
        tool = selected
    elif lower.startswith(("explain", "what is", "why", "how")):
        tool = "explain"
    elif lower.startswith(("solve", "calculate", "find")):
        tool = "solve"
    elif lower.startswith(("notes", "summarize")):
        tool = "notes"
    elif lower.startswith(("plan", "schedule")):
        tool = "planner"
    elif lower.startswith(("roast", "savage")):
        tool = "roast"
    elif lower.startswith(("mindmap", "mind map")):
        tool = "mindmap"
    elif lower.startswith(("derivation", "derive", "proof")):
        tool = "derivation"
    elif lower.startswith(("numerical", "calculate")):
        tool = "numerical"
    elif lower.startswith(("mcq", "quiz")):
        tool = "mcq"
    elif lower.startswith(("essay", "letter", "application")):
        tool = "essay"
    elif lower.startswith(("resume", "cv")):
        tool = "resume"
    elif lower.startswith(("career", "guidance")):
        tool = "career"
    elif lower.startswith(("tips", "sparsh")):
        tool = "tips"
    else:
        tool = "general"
    await process_question(update, context, text, tool)


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = " ".join(context.args).strip() if context.args else ""
    if q:
        await process_question(update, context, q)
    else:
        await reply(update, "Usage: `/ask your question`\n\n_ - made with love by Sparsh Singhal _")


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
        f"_ - made with love by Sparsh Singhal _",
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
        "_ - made with love by Sparsh Singhal _",
    )


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
        lines.append(f"\n📍 Your live rank: #{rank}")
    lines.append("\n_ - made with love by Sparsh Singhal _")
    await reply(update, "\n".join(lines))


async def upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reply(
        update,
        f"💎 *Unlock Pro – ₹{config.PRO_PRICE_INR} for 30 days*\n\n"
        "*All 28 Pro Features (by Sparsh Singhal):*\n"
        "1. Unlimited Doubt Solving\n"
        "2. Hinglish Savage Roast Mode\n"
        "3. NCERT Full Solutions\n"
        "4. PYQ (Last 10 Years style)\n"
        "5. Chapter-wise Notes\n"
        "6. Mind Maps Generator\n"
        "7. Formula Sheets\n"
        "8. Important Questions Bank\n"
        "9. Live Leaderboard Ranking\n"
        "10. XP & Level + Shield System\n"
        "11. Sound Effects + Haptic (Web)\n"
        "12. Diagram Explainer\n"
        "13. Derivation Breakdown\n"
        "14. Numerical Solver Step-by-Step\n"
        "15. MCQ Quiz Generator\n"
        "16. Mock Test Creator\n"
        "17. Essay / Letter / Application Writer\n"
        "18. Resume Builder\n"
        "19. Voice-style Answers\n"
        "20. Image Doubt / OCR Mode\n"
        "21. YouTube Video Summarizer style\n"
        "22. Career Guidance\n"
        "23. No Ads Experience\n"
        "24. Priority Answers\n"
        "25. Daily Missions & Rewards\n"
        "26. Ammo Crate Never Ends (Unlimited)\n"
        "27. Phone Linked Plan Tracking\n"
        "28. Founder Sparsh Tips + CODE+DRY RUN\n\n"
        f"Pay here: https://{config.VERCEL_URL}/pay?uid={update.effective_user.id}\n\n"
        "_ - made with love by Sparsh Singhal _",
    )


async def about_sparsh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reply(
        update,
        "👨‍💻 *About the Creator*\n\n"
        "*Sparsh Singhal*\n"
        "Builder of StudyGenie – India's gamified AI tutor for JEE, NEET, GATE & Boards.\n\n"
        "Now available on Telegram + WhatsApp + Web!\n\n"
        "Passionate about making quality education fun and accessible for every Indian student.\n\n"
        "_StudyGenie by Sparsh Singhal_ ❤️\n"
        "_ - made with love by Sparsh Singhal _",
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
        await reply(update, "📚 Type your question now!\n\n_ - made with love by Sparsh Singhal _")
    elif data == "menu_quiz":
        await reply(update, "🎯 Quiz mode coming very soon!\n\n_ - made with love by Sparsh Singhal _")
    elif data == "menu_tools":
        await reply(update, "🛠 *Study Tools*\n\n_ - made with love by Sparsh Singhal _", tools_menu(is_pro))
    elif data == "menu_progress":
        await progress(update, context)
    elif data == "menu_lb":
        await leaderboard(update, context)
    elif data == "menu_streak":
        await streak_cmd(update, context)
    elif data == "menu_quest":
        quest = db.set_daily_quest(user.id)
        await reply(
            update,
            f"🎮 *Daily Quest*\n\n{quest}\n\n+{config.XP_DAILY_QUEST} XP\n\n_ - made with love by Sparsh Singhal _",
        )
    elif data == "menu_badges":
        u = db.get_user(user.id) or {}
        badges = json.loads(u.get("badges", "[]"))
        text = "🏅 *Your Badges*\n\n" + ("\n".join(badges) if badges else "No badges yet.")
        text += "\n\n_ - made with love by Sparsh Singhal _"
        await reply(update, text)
    elif data == "menu_upgrade":
        await upgrade(update, context)
    elif data == "menu_prostatus":
        u = db.get_user(user.id) or {}
        await reply(
            update,
            f"👑 Pro active until: {u.get('pro_until', 'N/A')[:10]}\n\n_ - made with love by Sparsh Singhal _",
        )
    elif data == "menu_about":
        await about_sparsh(update, context)
    elif data.startswith("tool_"):
        tool = data.replace("tool_", "")
        # Pro-only tools gate
        pro_only = {
            "roast", "ncert", "mindmap", "important", "diagram", "derivation",
            "numerical", "mcq", "essay", "resume", "youtube", "career",
            "voice", "ocr", "mock", "tips",
        }
        if tool in pro_only and not is_pro:
            await reply(
                update,
                f"🔒 *{tool.title()}* is a Pro-only tool.\n\n"
                f"Upgrade to unlock all 28 Pro features for ₹{config.PRO_PRICE_INR}/30 days.\n\n"
                "_ - made with love by Sparsh Singhal _",
                InlineKeyboardMarkup(
                    [[InlineKeyboardButton(f"💎 Upgrade ₹{config.PRO_PRICE_INR}", callback_data="menu_upgrade")]]
                ),
            )
            return
        # Remember selected tool for next message (Redis = multi-worker safe)
        if user:
            db.set_tool(user.id, tool)
        if context.user_data is not None:
            context.user_data["selected_tool"] = tool
        nice = {
            "roast": "Savage Roast Mode 🔥",
            "ncert": "NCERT Full Solutions 📖",
            "mindmap": "Mind Map Generator 🧠",
            "important": "Important Questions Bank ⭐",
            "diagram": "Diagram Explainer 🖼",
            "derivation": "Derivation Breakdown 📐",
            "numerical": "Numerical Solver 🔢",
            "mcq": "MCQ Quiz Generator 🧪",
            "essay": "Essay / Letter Writer 📝",
            "resume": "Resume Builder 📄",
            "youtube": "YouTube Summarizer 🎬",
            "career": "Career Guidance 🎯",
            "voice": "Voice-style Answer 🎤",
            "ocr": "Image / OCR Doubt 📷",
            "mock": "Mock Test Creator 🧪",
            "tips": "Sparsh Tips + CODE+DRY RUN 💡",
            "explain": "Explain",
            "solve": "Solve",
            "notes": "Notes",
            "pyq": "PYQ",
            "formula": "Formulas",
            "planner": "Planner",
        }.get(tool, tool.title())
        await reply(
            update,
            f"✅ *{nice}* selected.\n\nAb apna sawaal / topic type karo 👇\n\n"
            "_ - made with love by Sparsh Singhal _",
        )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Telegram photo → Gemini Vision OCR (Pro only)."""
    user = update.effective_user
    if not user or not update.message or not update.message.photo:
        return
    uid = user.id
    is_pro = db.is_pro(uid)
    if not is_pro:
        await reply(
            update,
            f"📷 *Image Doubt Scan* is Pro-only.\n\n"
            f"Upgrade for ₹{config.PRO_PRICE_INR}/30 days to unlock OCR + all 28 features.\n\n"
            "_ - made with love by Sparsh Singhal _",
            InlineKeyboardMarkup(
                [[InlineKeyboardButton(f"💎 Upgrade ₹{config.PRO_PRICE_INR}", callback_data="menu_upgrade")]]
            ),
        )
        return

    await typing(update)
    try:
        photo = update.message.photo[-1]  # highest resolution
        file = await context.bot.get_file(photo.file_id)
        img_bytes = bytes(await file.download_as_bytearray())
        caption = (update.message.caption or "").strip()
        start = time.time()
        answer = run_ai(
            ai.answer_with_image,
            img_bytes,
            mime_type="image/jpeg",
            question=caption,
            tool="ocr",
            is_pro=True,
        )
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
        footer = (
            f"\n\n━━━━━━━━━━━━━━━\n"
            f"📷 OCR | ⚡ {elapsed:.1f}s | ⭐ +{xp_gain} XP (2× Pro) | Level {level}\n"
            f"_ - made with love by Sparsh Singhal _"
        )
        full = answer + footer
        if len(full) <= 4096:
            await reply(update, full)
        else:
            for i, chunk in enumerate([full[i : i + 4000] for i in range(0, len(full), 4000)]):
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
        app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, free_text))
        app.add_error_handler(error_handler)
        await app.initialize()
        telegram_app = app
        return app


# ============================================================================
# FLASK APP + SUPER GAMIFIED WEB FRONTEND
# ============================================================================

app = Flask(__name__)


@app.route("/sparsh.jpg")
def serve_photo():
    try:
        return send_from_directory(".", "sparsh.jpg")
    except Exception:
        return send_from_directory(".", "sparsh.jpg", conditional=True)


FRONTEND_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>StudyGenie by Sparsh Singhal – Gamified AI Tutor</title>
<meta name="theme-color" content="#0f172a">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #0b1220;
  --card: #151f32;
  --card2: #1a2740;
  --accent: #22d3ee;
  --accent2: #a78bfa;
  --text: #f1f5f9;
  --muted: #94a3b8;
  --success: #22c55e;
  --warn: #f59e0b;
  --danger: #ef4444;
  --radius: 16px;
}
* { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
html, body { height: 100%; }
body {
  font-family: 'Inter', system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  overflow-x: hidden;
}
header {
  background: linear-gradient(135deg, #0ea5e9 0%, #7c3aed 50%, #db2777 100%);
  padding: 0.85rem 1rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
  position: sticky;
  top: 0;
  z-index: 50;
  box-shadow: 0 4px 20px rgba(0,0,0,0.35);
}
.logo-wrap {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  cursor: pointer;
  user-select: none;
}
.logo-wrap img {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid #fff;
  box-shadow: 0 0 0 2px rgba(255,255,255,0.25);
}
.logo-text { font-weight: 800; font-size: 1.05rem; letter-spacing: -0.02em; }
.badge-live {
  background: rgba(0,0,0,0.25);
  backdrop-filter: blur(8px);
  color: #fff;
  padding: 0.3rem 0.7rem;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 600;
  border: 1px solid rgba(255,255,255,0.2);
}
main {
  flex: 1;
  max-width: 720px;
  margin: 0 auto;
  width: 100%;
  padding: 1rem;
  padding-bottom: 2rem;
}
.creator-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  background: linear-gradient(145deg, var(--card), var(--card2));
  border-radius: var(--radius);
  padding: 1rem;
  margin-bottom: 1rem;
  border: 1px solid #2a3a55;
  box-shadow: 0 8px 24px rgba(0,0,0,0.25);
  position: relative;
  overflow: hidden;
}
.creator-card::before {
  content: '';
  position: absolute;
  top: -50%;
  right: -20%;
  width: 160px;
  height: 160px;
  background: radial-gradient(circle, rgba(34,211,238,0.15), transparent 70%);
  pointer-events: none;
}
.creator-card img {
  width: 78px;
  height: 78px;
  border-radius: 50%;
  object-fit: cover;
  border: 3px solid var(--accent);
  box-shadow: 0 0 16px rgba(34,211,238,0.4);
  cursor: pointer;
  transition: transform 0.2s;
  flex-shrink: 0;
}
.creator-card img:active { transform: scale(0.95); }
.creator-info h3 { margin: 0; font-size: 1.15rem; font-weight: 700; }
.creator-info p { margin: 0.25rem 0 0; color: var(--muted); font-size: 0.85rem; line-height: 1.35; }
.creator-info .tag {
  display: inline-block;
  margin-top: 0.4rem;
  background: rgba(34,211,238,0.15);
  color: var(--accent);
  font-size: 0.7rem;
  font-weight: 600;
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
}
.card {
  background: var(--card);
  border-radius: var(--radius);
  padding: 1.1rem;
  margin-bottom: 1rem;
  border: 1px solid #2a3a55;
  box-shadow: 0 4px 16px rgba(0,0,0,0.2);
}
.stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.5rem;
}
.stat {
  text-align: center;
  background: var(--card2);
  border-radius: 12px;
  padding: 0.65rem 0.3rem;
  border: 1px solid #2a3a55;
}
.stat strong {
  display: block;
  font-size: 1.25rem;
  color: var(--accent);
  font-weight: 800;
}
.stat span { font-size: 0.68rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
.quota-bar {
  margin-top: 0.85rem;
  background: var(--card2);
  border-radius: 10px;
  padding: 0.7rem 0.9rem;
  border: 1px solid #2a3a55;
  font-size: 0.85rem;
}
.quota-bar .row { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.quota-bar .free-tag {
  background: rgba(34,197,94,0.15);
  color: var(--success);
  padding: 0.15rem 0.5rem;
  border-radius: 6px;
  font-weight: 600;
  font-size: 0.75rem;
}
.pro-pitch {
  margin-top: 0.6rem;
  font-size: 0.8rem;
  color: var(--muted);
  line-height: 1.4;
}
.pro-pitch strong { color: var(--warn); }
.chat-box {
  height: min(42vh, 380px);
  overflow-y: auto;
  background: #0a101c;
  border-radius: 12px;
  padding: 0.9rem;
  margin-bottom: 0.75rem;
  border: 1px solid #2a3a55;
  scroll-behavior: smooth;
  -webkit-overflow-scrolling: touch;
}
.msg {
  margin-bottom: 0.7rem;
  max-width: 90%;
  line-height: 1.45;
  font-size: 0.92rem;
  word-wrap: break-word;
  animation: fadeIn 0.25s ease;
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: none; }
}
.msg.user {
  margin-left: auto;
  background: linear-gradient(135deg, #0ea5e9, #0284c7);
  color: #fff;
  padding: 0.65rem 1rem;
  border-radius: 16px 16px 4px 16px;
  box-shadow: 0 2px 8px rgba(14,165,233,0.3);
}
.msg.bot {
  background: #1e2d45;
  padding: 0.65rem 1rem;
  border-radius: 16px 16px 16px 4px;
  border: 1px solid #2a3a55;
  white-space: pre-wrap;
}
.msg.bot.thinking {
  color: var(--accent);
  font-style: italic;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.msg.bot.thinking .dots span {
  display: inline-block;
  width: 6px;
  height: 6px;
  background: var(--accent);
  border-radius: 50%;
  animation: bounce 1.2s infinite ease-in-out;
}
.msg.bot.thinking .dots span:nth-child(2) { animation-delay: 0.15s; }
.msg.bot.thinking .dots span:nth-child(3) { animation-delay: 0.3s; }
@keyframes bounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}
.input-row {
  display: flex;
  gap: 0.5rem;
  align-items: stretch;
}
input#q {
  flex: 1;
  padding: 0.9rem 1rem;
  border-radius: 12px;
  border: 1px solid #2a3a55;
  background: var(--card2);
  color: white;
  font-size: 1rem;
  outline: none;
  transition: border-color 0.2s;
}
input#q:focus { border-color: var(--accent); }
button#sendBtn {
  background: linear-gradient(135deg, #22d3ee, #0ea5e9);
  color: #0f172a;
  border: none;
  padding: 0 1.25rem;
  border-radius: 12px;
  font-weight: 700;
  cursor: pointer;
  font-size: 0.95rem;
  transition: transform 0.15s, box-shadow 0.15s;
  white-space: nowrap;
}
button#sendBtn:active { transform: scale(0.97); }
button#sendBtn:disabled { opacity: 0.6; cursor: not-allowed; }
.pro-btn {
  display: block;
  margin-top: 0.85rem;
  background: linear-gradient(135deg, #f59e0b, #ef4444);
  color: white;
  padding: 0.75rem 1.2rem;
  border-radius: 12px;
  text-decoration: none;
  font-weight: 700;
  text-align: center;
  box-shadow: 0 4px 14px rgba(245,158,11,0.35);
  transition: transform 0.15s;
}
.pro-btn:active { transform: scale(0.98); }
.leaderboard-card h3 {
  font-size: 1rem;
  margin-bottom: 0.7rem;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.lb-list { list-style: none; }
.lb-item {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.5rem 0.4rem;
  border-bottom: 1px solid #1e2d45;
  font-size: 0.88rem;
}
.lb-item:last-child { border-bottom: none; }
.lb-rank { width: 28px; text-align: center; font-weight: 700; }
.lb-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lb-xp { color: var(--accent); font-weight: 700; font-size: 0.85rem; }
.lb-level { color: var(--muted); font-size: 0.75rem; }
.live-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  background: var(--success);
  border-radius: 50%;
  animation: pulse 1.5s infinite;
  margin-right: 0.25rem;
}
@keyframes pulse {
  0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(34,197,94,0.5); }
  50% { opacity: 0.7; box-shadow: 0 0 0 6px rgba(34,197,94,0); }
}
footer {
  text-align: center;
  padding: 1.25rem 1rem 1.5rem;
  color: var(--muted);
  font-size: 0.82rem;
  line-height: 1.5;
}
footer strong { color: var(--accent); }
.dev-panel {
  display: none;
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: #0a101c;
  border-top: 2px solid var(--accent);
  padding: 1rem;
  z-index: 100;
  max-height: 45vh;
  overflow-y: auto;
  box-shadow: 0 -8px 30px rgba(0,0,0,0.5);
}
.dev-panel.open { display: block; }
.dev-panel h4 { color: var(--accent); margin-bottom: 0.6rem; font-size: 0.95rem; }
.dev-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.5rem; margin-bottom: 0.75rem; }
.dev-stat {
  background: var(--card);
  border-radius: 10px;
  padding: 0.6rem;
  text-align: center;
  border: 1px solid #2a3a55;
}
.dev-stat strong { display: block; font-size: 1.2rem; color: var(--accent); }
.dev-stat span { font-size: 0.7rem; color: var(--muted); }
.dev-close {
  position: absolute;
  top: 0.6rem;
  right: 0.8rem;
  background: transparent;
  border: none;
  color: var(--muted);
  font-size: 1.2rem;
  cursor: pointer;
}
.sound-toggle {
  background: rgba(0,0,0,0.25);
  border: 1px solid rgba(255,255,255,0.2);
  color: #fff;
  border-radius: 999px;
  padding: 0.3rem 0.6rem;
  font-size: 0.75rem;
  cursor: pointer;
  margin-left: 0.4rem;
}
@media (max-width: 480px) {
  .stats { grid-template-columns: repeat(2, 1fr); }
  .creator-card img { width: 64px; height: 64px; }
  .logo-text { font-size: 0.95rem; }
  .chat-box { height: min(38vh, 320px); }
  .msg { max-width: 92%; font-size: 0.9rem; }
}
</style>
</head>
<body>
<header>
  <div class="logo-wrap" id="logoArea" title="StudyGenie by Sparsh Singhal">
    <img src="/sparsh.jpg" alt="Sparsh" id="headerPhoto"
         onerror="this.src='https://raw.githubusercontent.com/sparshsinghal2025-ops/studygenie/main/sparsh.jpg'">
    <div class="logo-text">🎓 StudyGenie</div>
  </div>
  <div style="display:flex;align-items:center;">
    <div class="badge-live"><span class="live-dot"></span> Live</div>
    <button class="sound-toggle" id="soundBtn" title="Toggle sounds">🔊</button>
  </div>
</header>

<main>
  <div class="creator-card">
    <img src="/sparsh.jpg" alt="Sparsh Singhal" id="creatorPhoto"
         onerror="this.src='https://raw.githubusercontent.com/sparshsinghal2025-ops/studygenie/main/sparsh.jpg'">
    <div class="creator-info">
      <h3>Sparsh Singhal</h3>
      <p>Creator of StudyGenie • India's most fun gamified AI tutor for JEE • NEET • GATE • Boards</p>
      <span class="tag">Made with ❤️ by Sparsh Singhal</span>
    </div>
  </div>

  <div class="card">
    <div class="stats">
      <div class="stat"><strong id="level">1</strong><span>Level</span></div>
      <div class="stat"><strong id="xp">0</strong><span>XP</span></div>
      <div class="stat"><strong id="streak">0</strong><span>Streak</span></div>
      <div class="stat"><strong id="rank">—</strong><span>Rank</span></div>
    </div>
    <div class="quota-bar">
      <div class="row">
        <span>🆓 Free plan</span>
        <span class="free-tag" id="quotaText">{{ free_daily }}/day • {{ free_lifetime }} lifetime</span>
      </div>
      <div class="pro-pitch">
        <strong>Pro (₹{{ price }}/mo) – All 28 Features:</strong> Unlimited doubts • Savage Roast • NCERT • PYQ • Mind Maps • Diagrams • Derivations • Numerical Solver • MCQ + Mock Tests • Essay/Resume • YT Summary • Career Guide • Sparsh Tips + CODE+DRY RUN • 2× XP • Priority & more
      </div>
    </div>
  </div>

  <div class="card">
    <div class="chat-box" id="chat"></div>
    <div style="display:flex;gap:0.5rem;margin-bottom:0.6rem;flex-wrap:wrap;align-items:center;">
      <select id="toolSelect" style="flex:1;min-width:140px;padding:0.65rem 0.75rem;border-radius:10px;border:1px solid #2a3a55;background:var(--card2);color:#fff;font-size:0.9rem;">
        <option value="general">📚 General Ask</option>
        <option value="explain">💡 Explain</option>
        <option value="solve">🧮 Solve</option>
        <option value="notes">📝 Notes</option>
        <option value="pyq">📋 PYQ</option>
        <option value="formula">📐 Formulas</option>
        <option value="planner">📅 Planner</option>
        <option value="roast">🔥 Savage Roast (Pro)</option>
        <option value="ncert">📖 NCERT (Pro)</option>
        <option value="mindmap">🧠 Mind Map (Pro)</option>
        <option value="important">⭐ Important Qs (Pro)</option>
        <option value="diagram">🖼 Diagram (Pro)</option>
        <option value="derivation">📐 Derivation (Pro)</option>
        <option value="numerical">🔢 Numerical (Pro)</option>
        <option value="mcq">🧪 MCQ Quiz (Pro)</option>
        <option value="mock">🧪 Mock Test (Pro)</option>
        <option value="essay">📝 Essay/Letter (Pro)</option>
        <option value="resume">📄 Resume (Pro)</option>
        <option value="youtube">🎬 YT Summary (Pro)</option>
        <option value="career">🎯 Career (Pro)</option>
        <option value="ocr">📷 Image OCR (Pro)</option>
        <option value="tips">💡 Sparsh Tips (Pro)</option>
        <option value="voice">🎤 Voice Style (Pro)</option>
      </select>
      <label for="imgInput" style="cursor:pointer;background:var(--card2);border:1px solid #2a3a55;border-radius:10px;padding:0.65rem 0.9rem;font-size:0.85rem;color:var(--accent);white-space:nowrap;" title="Upload question photo (Pro)">
        📷 Image
      </label>
      <input type="file" id="imgInput" accept="image/*" style="display:none;">
    </div>
    <div id="imgPreview" style="display:none;margin-bottom:0.6rem;align-items:center;gap:0.5rem;">
      <img id="imgThumb" style="max-height:64px;border-radius:8px;border:1px solid #2a3a55;">
      <button type="button" onclick="clearImage()" style="background:transparent;border:none;color:var(--danger);cursor:pointer;font-size:0.85rem;">✕ Remove</button>
    </div>
    <div class="input-row">
      <input id="q" placeholder="Ask any JEE / NEET question..." autocomplete="off" enterkeyhint="send">
      <button id="sendBtn" onclick="ask()">Send</button>
    </div>
    <a class="pro-btn" href="/pay" id="proLink">💎 Unlock Pro – ₹{{ price }}/mo • All 28 Features</a>
  </div>

  <div class="card leaderboard-card">
    <h3><span class="live-dot"></span> Live Leaderboard (by XP)</h3>
    <ul class="lb-list" id="lbList">
      <li class="lb-item" style="color:var(--muted);">Loading rankings…</li>
    </ul>
  </div>
</main>

<footer>
  <strong>StudyGenie by Sparsh Singhal</strong><br>
  Available on Telegram • WhatsApp • Web<br>
  Made with ❤️ for every Indian student<br>
  <span style="opacity:0.7;">- made with love by Sparsh Singhal</span>
</footer>

<div class="dev-panel" id="devPanel">
  <button class="dev-close" onclick="closeDev()">✕</button>
  <h4>🛠 Dev Mode (Sparsh only)</h4>
  <div class="dev-stats">
    <div class="dev-stat"><strong id="devUsers">—</strong><span>Total Users</span></div>
    <div class="dev-stat"><strong id="devQs">—</strong><span>Total Qs</span></div>
    <div class="dev-stat"><strong id="devOnline">—</strong><span>On Leaderboard</span></div>
  </div>
  <p style="font-size:0.8rem;color:var(--muted);">Live tracking • Secret access only</p>
</div>

<script>
// ---------- Sound system ----------
let soundOn = localStorage.getItem('sg_sound') !== '0';
const soundBtn = document.getElementById('soundBtn');
soundBtn.textContent = soundOn ? '🔊' : '🔇';

function toggleSound() {
  soundOn = !soundOn;
  localStorage.setItem('sg_sound', soundOn ? '1' : '0');
  soundBtn.textContent = soundOn ? '🔊' : '🔇';
  playTone(soundOn ? 880 : 220, 0.08);
}
soundBtn.addEventListener('click', toggleSound);

let audioCtx = null;
function getCtx() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  return audioCtx;
}
function playTone(freq, dur, type='sine', vol=0.08) {
  if (!soundOn) return;
  try {
    const ctx = getCtx();
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = type;
    o.frequency.value = freq;
    g.gain.value = vol;
    o.connect(g);
    g.connect(ctx.destination);
    o.start();
    g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + dur);
    o.stop(ctx.currentTime + dur);
  } catch(e) {}
}
function sfxClick() { playTone(600, 0.06, 'square', 0.06); }
function sfxSend() { playTone(720, 0.08, 'sine', 0.07); playTone(980, 0.1, 'sine', 0.05); }
function sfxThink() { playTone(440, 0.12, 'triangle', 0.05); }
function sfxDone() { playTone(523, 0.1); setTimeout(()=>playTone(659, 0.12), 80); setTimeout(()=>playTone(784, 0.15), 160); }
function sfxError() { playTone(200, 0.2, 'sawtooth', 0.06); }
function sfxLevel() { playTone(880, 0.15); setTimeout(()=>playTone(1100, 0.2), 100); }

// ---------- Chat & API ----------
const chat = document.getElementById('chat');
const input = document.getElementById('q');
const sendBtn = document.getElementById('sendBtn');
let localXp = parseInt(localStorage.getItem('sg_xp') || '0', 10);
let localLevel = parseInt(localStorage.getItem('sg_level') || '1', 10);
let localStreak = parseInt(localStorage.getItem('sg_streak') || '0', 10);

function updateStatsUI() {
  document.getElementById('xp').textContent = localXp;
  document.getElementById('level').textContent = localLevel;
  document.getElementById('streak').textContent = localStreak;
}
updateStatsUI();

function addMsg(text, who, isThinking=false) {
  const d = document.createElement('div');
  d.className = 'msg ' + who + (isThinking ? ' thinking' : '');
  if (isThinking) {
    d.innerHTML = text + ' <span class="dots"><span></span><span></span><span></span></span>';
  } else {
    d.innerText = text;
  }
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
  return d;
}

let pendingImageBase64 = null;
let pendingImageMime = 'image/jpeg';

document.getElementById('imgInput').addEventListener('change', function(e) {
  const file = e.target.files[0];
  if (!file) return;
  if (file.size > 4 * 1024 * 1024) {
    alert('Image too large (max 4 MB)');
    return;
  }
  const reader = new FileReader();
  reader.onload = function(ev) {
    const dataUrl = ev.target.result;
    pendingImageBase64 = dataUrl.split(',')[1];
    pendingImageMime = file.type || 'image/jpeg';
    document.getElementById('imgThumb').src = dataUrl;
    document.getElementById('imgPreview').style.display = 'flex';
    document.getElementById('toolSelect').value = 'ocr';
    sfxClick();
  };
  reader.readAsDataURL(file);
});

function clearImage() {
  pendingImageBase64 = null;
  pendingImageMime = 'image/jpeg';
  document.getElementById('imgInput').value = '';
  document.getElementById('imgPreview').style.display = 'none';
  document.getElementById('imgThumb').src = '';
}

async function ask() {
  const q = input.value.trim();
  const tool = document.getElementById('toolSelect').value || 'general';
  if (!q && !pendingImageBase64) return;
  sfxSend();
  const displayQ = q || (pendingImageBase64 ? '[📷 Image uploaded]' : '');
  addMsg(displayQ + (tool !== 'general' ? '  ·  ' + tool : ''), 'user');
  input.value = '';
  sendBtn.disabled = true;
  const thinkEl = addMsg('Sparsh Singhal ka bot StudyGenie abhi soch raha hai', 'bot', true);
  sfxThink();

  try {
    const payload = {
      question: q,
      tool: tool,
      client_id: getClientId()
    };
    if (pendingImageBase64) {
      payload.image_base64 = pendingImageBase64;
      payload.image_mime = pendingImageMime;
    }
    const res = await fetch('/api/webask', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    thinkEl.classList.remove('thinking');
    thinkEl.innerHTML = '';
    thinkEl.innerText = data.answer || 'Error, try again.';
    clearImage();
    if (data.xp !== undefined) {
      const oldLevel = localLevel;
      localXp = data.xp;
      localLevel = data.level || Math.floor(localXp / 100) + 1;
      localStorage.setItem('sg_xp', localXp);
      localStorage.setItem('sg_level', localLevel);
      updateStatsUI();
      if (localLevel > oldLevel) sfxLevel();
      else sfxDone();
    } else {
      sfxDone();
    }
    if (data.rank) document.getElementById('rank').textContent = '#' + data.rank;
    if (data.quota) {
      const qEl = document.getElementById('quotaText');
      if (data.quota.daily_left === -1) {
        qEl.textContent = '∞ Pro Unlimited';
        qEl.style.color = '#f59e0b';
      } else {
        qEl.textContent = data.quota.daily_left + ' left today • ' + data.quota.lifetime_left + ' lifetime';
      }
    }
    loadLeaderboard();
  } catch(e) {
    thinkEl.classList.remove('thinking');
    thinkEl.innerText = 'Network error. Please try again.';
    sfxError();
  }
  sendBtn.disabled = false;
  chat.scrollTop = chat.scrollHeight;
}

input.addEventListener('keypress', e => { if (e.key === 'Enter') ask(); });
input.addEventListener('focus', () => sfxClick());

function getClientId() {
  let id = localStorage.getItem('sg_client');
  if (!id) {
    id = 'web_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
    localStorage.setItem('sg_client', id);
  }
  return id;
}

// ---------- Live Leaderboard ----------
async function loadLeaderboard() {
  try {
    const res = await fetch('/api/leaderboard');
    const data = await res.json();
    const list = document.getElementById('lbList');
    if (!data.board || !data.board.length) {
      list.innerHTML = '<li class="lb-item" style="color:var(--muted);">Be the first on the board!</li>';
      return;
    }
    list.innerHTML = data.board.map(e => {
      const medal = e.rank === 1 ? '🥇' : e.rank === 2 ? '🥈' : e.rank === 3 ? '🥉' : e.rank + '.';
      return `<li class="lb-item">
        <span class="lb-rank">${medal}</span>
        <span class="lb-name">${escapeHtml(e.name)}</span>
        <span class="lb-level">L${e.level}</span>
        <span class="lb-xp">${e.xp} XP</span>
      </li>`;
    }).join('');
  } catch(e) {}
}
function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
loadLeaderboard();
setInterval(loadLeaderboard, 25000);

// ---------- Dev Mode: 5 clicks + secret (secret checked only on server) ----------
let clickCount = 0;
let clickTimer = null;

function onDevClick() {
  sfxClick();
  clickCount++;
  if (clickTimer) clearTimeout(clickTimer);
  clickTimer = setTimeout(() => { clickCount = 0; }, 2500);
  if (clickCount >= 5) {
    clickCount = 0;
    const code = prompt('🔐 Enter developer secret code:');
    if (code && code.trim()) {
      openDev(code.trim());
    } else {
      sfxError();
    }
  }
}
document.getElementById('logoArea').addEventListener('click', onDevClick);
document.getElementById('creatorPhoto').addEventListener('click', onDevClick);
document.getElementById('headerPhoto').addEventListener('click', onDevClick);

async function openDev(code) {
  try {
    const res = await fetch('/api/dev/stats?code=' + encodeURIComponent(code));
    const data = await res.json();
    if (data.ok) {
      document.getElementById('devUsers').textContent = data.total_users;
      document.getElementById('devQs').textContent = data.total_questions;
      document.getElementById('devOnline').textContent = data.online_approx;
      document.getElementById('devPanel').classList.add('open');
      sfxDone();
    } else {
      sfxError();
      alert('Access denied.');
    }
  } catch(e) {
    sfxError();
    alert('Access denied.');
  }
}
function closeDev() {
  document.getElementById('devPanel').classList.remove('open');
  sfxClick();
}

// Welcome message
setTimeout(() => {
  addMsg('Namaste! 👋 Main StudyGenie hoon – Sparsh Singhal ka gamified AI tutor.\\n\\nKoi bhi JEE/NEET sawaal poochho. Free plan: {{ free_daily }} questions/day & {{ free_lifetime }} lifetime.\\n\\nPro le lo for unlimited power! 🚀\\n\\n- made with love by Sparsh Singhal', 'bot');
}, 400);
</script>
</body>
</html>
"""


@app.route("/")
def home():
    return render_template_string(
        FRONTEND_HTML,
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
            redis_ok = False
    status = 200 if redis_ok or not config.REDIS_URL else 503
    body = {
        "ok": redis_ok or not config.REDIS_URL,
        "redis": redis_ok,
        "gemini": ai.client is not None,
        "whatsapp": bool(config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_NUMBER_ID),
        "razorpay": bool(config.RAZORPAY_KEY_ID and config.RAZORPAY_KEY_SECRET),
        "ai_pool_workers": int(os.getenv("AI_POOL_WORKERS", "8")),
        "version": "StudyGenie by Sparsh Singhal v2.2 (thousands-ready)",
        "creator": "Sparsh Singhal",
    }
    return jsonify(body), status


@app.route("/api/webask", methods=["POST"])
def web_ask():
    data = request.get_json(silent=True) or {}
    q = (data.get("question") or "").strip()
    tool = (data.get("tool") or "general").strip().lower()
    client_id = (data.get("client_id") or request.remote_addr or "anon").strip()
    image_b64 = data.get("image_base64") or ""
    image_mime = (data.get("image_mime") or "image/jpeg").strip()

    if is_rate_limited(f"web:{client_id}", max_calls=10, window_sec=60):
        return jsonify(
            {"answer": "Too many requests. Please wait a minute.\n\n- made with love by Sparsh Singhal"}
        ), 429

    if not q and not image_b64:
        return jsonify({"answer": "Please type a question or upload an image"}), 400

    uid = f"web:{client_id}"
    udata = db.ensure_user(uid, full_name="Web Student", platform="web")
    is_pro = db.is_pro(uid)

    pro_only = {
        "roast", "ncert", "mindmap", "important", "diagram", "derivation",
        "numerical", "mcq", "essay", "resume", "youtube", "career",
        "voice", "ocr", "mock", "tips",
    }
    if (tool in pro_only or image_b64) and not is_pro:
        return jsonify(
            {
                "answer": (
                    f"🔒 This tool / Image OCR is Pro-only.\n\n"
                    f"Upgrade for ₹{config.PRO_PRICE_INR}/30 days to unlock all 28 features.\n\n"
                    "- made with love by Sparsh Singhal"
                )
            }
        )

    if not is_pro:
        can, quota = db.check_quota(uid)
        if not can:
            return jsonify(
                {
                    "answer": (
                        f"❌ Quota finished!\n\nFree plan: {config.FREE_DAILY}/day & "
                        f"{config.FREE_LIFETIME} lifetime.\nUpgrade to Pro for unlimited access.\n\n"
                        "- made with love by Sparsh Singhal"
                    ),
                    "quota": quota,
                }
            )

    start = time.time()
    answer = None
    if image_b64:
        try:
            import base64 as b64mod
            img_bytes = b64mod.b64decode(image_b64)
            answer = run_ai(
                ai.answer_with_image,
                img_bytes,
                mime_type=image_mime,
                question=q,
                tool="ocr",
                is_pro=is_pro,
            )
        except Exception as e:
            logger.error("Image decode error: %s", e)
            answer = "Could not read the image. Please try another photo."
    else:
        answer = run_ai(ai.answer, q, tool, is_pro=is_pro)
    elapsed = time.time() - start

    if not answer:
        return jsonify(
            {"answer": "😔 Couldn't generate answer. Try again.\n\n- made with love by Sparsh Singhal"}
        )

    if not is_pro:
        db.consume_quota(uid)

    xp_gain = config.XP_QUESTION * (2 if is_pro else 1)
    xp, level = db.add_xp(uid, xp_gain)
    questions = int(udata.get("questions_asked", 0)) + 1
    udata["questions_asked"] = str(questions)
    db.save_user(uid, udata)

    if questions == 1:
        db.add_badge(uid, "First Step 🐣")
    if questions >= 50:
        db.add_badge(uid, "Knowledge Seeker 📚")
    if level >= 5:
        db.add_badge(uid, "Rising Star ⭐")

    _, quota = db.check_quota(uid)
    rank = db.get_rank(uid)

    footer = (
        f"\n\n━━━━━━━━━━━━━━━\n"
        f"⚡ {elapsed:.1f}s | ⭐ +{xp_gain} XP{' (2× Pro)' if is_pro else ''} | Level {level}\n"
        f"- made with love by Sparsh Singhal"
    )
    full = answer + footer
    return jsonify(
        {
            "answer": full,
            "xp": xp,
            "level": level,
            "rank": rank,
            "quota": quota,
            "elapsed": round(elapsed, 2),
        }
    )


@app.route("/api/leaderboard")
def api_leaderboard():
    board = db.get_leaderboard(15)
    return jsonify({"board": board, "live": True})


@app.route("/api/dev/stats")
def dev_stats():
    code = request.args.get("code", "")
    if code != config.DEV_SECRET:
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    stats = db.get_stats()
    return jsonify({"ok": True, **stats})


@app.route("/api/dev/activate-pro", methods=["POST"])
def dev_activate_pro():
    """Force-activate Pro (admin only) – useful if webhook fails."""
    data = request.get_json(silent=True) or {}
    code = data.get("code") or request.args.get("code", "")
    if code != config.DEV_SECRET:
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    uid = str(data.get("uid") or "").strip()
    days = int(data.get("days") or 30)
    if not uid:
        return jsonify({"ok": False, "error": "uid required"}), 400
    ok = db.activate_pro(uid, days=days)
    if ok:
        db.add_badge(uid, "Pro Warrior 👑")
    return jsonify({"ok": ok, "uid": uid, "days": days})


@app.route("/api/razorpay/create-order", methods=["POST"])
def razorpay_create_order():
    """Create a Razorpay order for Pro upgrade."""
    if not config.RAZORPAY_KEY_ID or not config.RAZORPAY_KEY_SECRET:
        return jsonify({"ok": False, "error": "Razorpay keys not configured"}), 500
    data = request.get_json(silent=True) or {}
    uid = str(data.get("uid") or data.get("user_id") or "0").strip()
    amount_paise = int(config.PRO_PRICE_INR) * 100
    try:
        import base64 as b64mod
        auth = b64mod.b64encode(
            f"{config.RAZORPAY_KEY_ID}:{config.RAZORPAY_KEY_SECRET}".encode()
        ).decode()
        payload = {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": f"sg_{uid}_{int(time.time())}"[:40],
            "notes": {"user_id": uid, "product": "StudyGenie Pro 30 days"},
        }
        r = requests.post(
            "https://api.razorpay.com/v1/orders",
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
        if r.status_code not in (200, 201):
            logger.error("Razorpay order fail: %s %s", r.status_code, r.text)
            return jsonify({"ok": False, "error": "Could not create order"}), 500
        order = r.json()
        return jsonify(
            {
                "ok": True,
                "order_id": order["id"],
                "amount": order["amount"],
                "currency": order["currency"],
                "key_id": config.RAZORPAY_KEY_ID,
                "uid": uid,
            }
        )
    except Exception as e:
        logger.error("Razorpay create-order: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/pay")
def pay_page():
    uid = request.args.get("uid", "0")
    key_id = config.RAZORPAY_KEY_ID or ""
    price = config.PRO_PRICE_INR
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Upgrade – StudyGenie by Sparsh Singhal</title>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
<style>
body {{ font-family: Inter, system-ui, sans-serif; background:#0b1220; color:#f1f5f9; text-align:center; padding:2rem 1rem; margin:0; }}
img {{ width:96px; height:96px; border-radius:50%; border:3px solid #22d3ee; margin-bottom:1rem; object-fit:cover; box-shadow:0 0 20px rgba(34,211,238,0.4); }}
h1 {{ font-size:1.6rem; margin:0.5rem 0; }}
.features {{ text-align:left; max-width:360px; margin:1.5rem auto; background:#151f32; border-radius:16px; padding:1.2rem; border:1px solid #2a3a55; max-height:280px; overflow-y:auto; }}
.features li {{ margin:0.4rem 0; font-size:0.9rem; }}
.price {{ font-size:1.8rem; color:#f59e0b; font-weight:800; margin:1rem 0; }}
a.back {{ color:#22d3ee; text-decoration:none; }}
#payBtn {{
  background: linear-gradient(135deg, #f59e0b, #ef4444);
  color: #fff; border: none; padding: 0.9rem 2rem; border-radius: 12px;
  font-weight: 700; font-size: 1.05rem; cursor: pointer; margin-top: 1rem;
  box-shadow: 0 4px 16px rgba(245,158,11,0.4);
}}
#payBtn:disabled {{ opacity: 0.6; cursor: not-allowed; }}
#status {{ margin-top: 1rem; font-size: 0.9rem; color: #94a3b8; min-height: 1.4em; }}
</style>
</head>
<body>
<img src="/sparsh.jpg" alt="Sparsh Singhal" onerror="this.src='https://raw.githubusercontent.com/sparshsinghal2025-ops/studygenie/main/sparsh.jpg'">
<h1>💎 StudyGenie Pro</h1>
<p>Created by <strong>Sparsh Singhal</strong></p>
<div class="price">₹{price} / 30 days</div>
<div class="features">
<ul>
<li>✅ Unlimited Doubt Solving</li>
<li>✅ Hinglish Savage Roast Mode</li>
<li>✅ NCERT Full Solutions</li>
<li>✅ PYQ + Chapter Notes + Mind Maps</li>
<li>✅ Formula Sheets + Important Qs</li>
<li>✅ Diagram + Derivation + Numerical Solver</li>
<li>✅ MCQ Quiz + Mock Test Creator</li>
<li>✅ Essay / Letter / Resume Builder</li>
<li>✅ Image OCR (photo doubt scan)</li>
<li>✅ YT Summarizer + Career Guide</li>
<li>✅ 2× XP + Priority + No Ads</li>
<li>✅ Sparsh Tips + CODE+DRY RUN</li>
<li>✅ + all other Pro features</li>
</ul>
</div>
<p>Works on Telegram + WhatsApp + Web</p>
<p><small>User ID: {uid}</small></p>
<button id="payBtn" onclick="startPay()">Pay ₹{price} Securely</button>
<div id="status"></div>
<p style="margin-top:1.5rem;"><a class="back" href="/">← Back to StudyGenie</a></p>
<p style="color:#94a3b8;font-size:0.85rem;margin-top:2rem;">- made with love by Sparsh Singhal</p>
<script>
const UID = {json.dumps(uid)};
const KEY_ID = {json.dumps(key_id)};
const PRICE = {price};

async function startPay() {{
  const btn = document.getElementById('payBtn');
  const status = document.getElementById('status');
  if (!KEY_ID) {{
    status.textContent = 'Payment gateway not configured. Contact support.';
    return;
  }}
  btn.disabled = true;
  status.textContent = 'Creating secure order…';
  try {{
    const res = await fetch('/api/razorpay/create-order', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ uid: UID }})
    }});
    const data = await res.json();
    if (!data.ok) {{
      status.textContent = data.error || 'Could not create order';
      btn.disabled = false;
      return;
    }}
    const options = {{
      key: data.key_id,
      amount: data.amount,
      currency: data.currency,
      name: 'StudyGenie by Sparsh Singhal',
      description: 'Pro – 30 days unlimited',
      order_id: data.order_id,
      notes: {{ user_id: UID }},
      handler: function (response) {{
        status.textContent = '✅ Payment successful! Pro will activate shortly.';
        status.style.color = '#22c55e';
        btn.textContent = 'Paid ✓';
      }},
      theme: {{ color: '#0ea5e9' }},
      modal: {{
        ondismiss: function() {{
          btn.disabled = false;
          status.textContent = 'Payment cancelled.';
        }}
      }}
    }};
    const rzp = new Razorpay(options);
    rzp.on('payment.failed', function (resp) {{
      status.textContent = 'Payment failed. Please try again.';
      status.style.color = '#ef4444';
      btn.disabled = false;
    }});
    rzp.open();
    status.textContent = '';
  }} catch (e) {{
    status.textContent = 'Network error. Please try again.';
    btn.disabled = false;
  }}
}}
</script>
</body>
</html>
"""


@app.route("/api/razorpay/webhook", methods=["POST"])
def razorpay_webhook():
    try:
        body = request.get_data()
        received_sig = request.headers.get("X-Razorpay-Signature", "")
        if config.RAZORPAY_WEBHOOK_SECRET:
            expected = hmac.new(
                config.RAZORPAY_WEBHOOK_SECRET.encode(),
                body,
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected, received_sig):
                logger.warning("Invalid Razorpay signature")
                return jsonify({"ok": False}), 400

        payload = request.get_json(force=True)
        event = payload.get("event")
        if event == "payment.captured":
            entity = (
                payload.get("payload", {})
                .get("payment", {})
                .get("entity", {})
            )
            payment_id = entity.get("id", "")
            notes = entity.get("notes", {}) or {}
            uid = notes.get("user_id", "")
            # Idempotency – ignore duplicate webhook deliveries
            if payment_id and not db.mark_payment_processed(payment_id):
                logger.info("Duplicate payment webhook ignored: %s", payment_id)
                return jsonify({"ok": True, "duplicate": True})
            if uid:
                db.activate_pro(uid, days=30)
                db.add_badge(uid, "Pro Warrior 👑")
                logger.info("Pro activated for %s (payment %s)", uid, payment_id)
        return jsonify({"ok": True})
    except Exception as e:
        logger.error("Razorpay webhook: %s", e)
        return jsonify({"ok": False}), 500


@app.route("/api/whatsapp", methods=["GET", "POST"])
def whatsapp_webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == config.WHATSAPP_VERIFY_TOKEN:
            logger.info("WhatsApp webhook verified")
            return challenge, 200
        return "Forbidden", 403

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

        # Rate limit by user id
        uid = "tg"
        try:
            uid = str(
                data.get("message", {}).get("from", {}).get("id")
                or data.get("callback_query", {}).get("from", {}).get("id")
                or "tg"
            )
        except Exception:
            pass
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
        return jsonify(
            {
                "ok": True,
                "telegram_webhook": u,
                "whatsapp_webhook": f"https://{config.VERCEL_URL}/api/whatsapp",
                "creator": "Sparsh Singhal",
            }
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
