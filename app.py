"""
StudyGenie by Sparsh Singhal
Fully Gamified Multi-Platform E-Learning Bot
Telegram + WhatsApp + Web Dashboard
Groq (Primary) + Gemini (Fallback) | All Exams | Stats | Razorpay Pro
UI: Branding + Pro Modal + Sounds + Dev Mode + Name Input + Markdown Render
"""

from __future__ import annotations

import asyncio
import base64
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
        self.GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()
        self.GEMINI_FLASH_LITE_MODEL = os.getenv("GEMINI_FLASH_LITE_MODEL", "gemini-3.1-flash-lite").strip()
        self.GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
        self.GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip()
        self.AI_PRIMARY = os.getenv("AI_PRIMARY", "groq").strip().lower()

        # --- Extra fallback providers (reliability chain) -----------------
        # DeepSeek: NOT a true free tier (verified) — pay-as-you-go at
        # ~$0.14/1M input tokens, with a one-time 5M-token grant for new
        # accounts. Still cheap enough to sit as a fallback with near-zero
        # cost at low traffic. https://api-docs.deepseek.com
        self.DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
        self.DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()
        self.DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()

        # OpenRouter: genuinely free models exist (":free" suffix), rate
        # limited to ~20 req/min and 50 req/day per key (1000/day after a
        # one-time $10 top-up). We rotate through several free models so a
        # single model being saturated doesn't take the whole fallback down.
        self.OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
        self.OPENROUTER_MODELS = [
            m.strip() for m in os.getenv(
                "OPENROUTER_MODELS",
                "meta-llama/llama-3.3-70b-instruct:free,"
                "qwen/qwen3-next-80b-a3b-instruct:free,"
                "mistralai/mistral-small-3.1-24b-instruct:free",
            ).split(",") if m.strip()
        ]
        self.OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "https://studygenie.app").strip()
        self.OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "StudyGenie by Sparsh Singhal").strip()

        self.FREE_DAILY = int(os.getenv("FREE_DAILY_QUESTIONS", "4"))
        self.FREE_LIFETIME = int(os.getenv("FREE_LIFETIME_QUESTIONS", "12"))

        self.PRO_PRICE_INR = int(os.getenv("PRO_PRICE_INR", "49"))
        self.RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "").strip()
        self.RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
        self.RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "").strip()

        self.WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "").strip()
        self.WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
        self.WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "studygenie_sparsh").strip()
        self.WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v20.0")

        self.XP_QUESTION = 15
        self.CACHE_TTL = 3600
        # No hardcoded fallback — dev endpoints (/api/dev/*, /api/debug/ai)
        # stay disabled until you explicitly set DEV_SECRET in your env.
        self.DEV_SECRET = os.getenv("DEV_SECRET", "").strip()
        self.validate()

    def validate(self) -> None:
        if not self.BOT_TOKEN:
            logger.error("BOT_TOKEN is missing")
        if not self.GROQ_API_KEY and not self.GOOGLE_API_KEY:
            logger.error("Neither GROQ_API_KEY nor GOOGLE_API_KEY is set!")


config = Config()

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

_AI_POOL = ThreadPoolExecutor(max_workers=int(os.getenv("AI_POOL_WORKERS", "6")), thread_name_prefix="ai")
_AI_TIMEOUT = float(os.getenv("AI_TIMEOUT_SEC", "45"))
_rate_lock = Lock()
_rate_buckets: dict[str, list[float]] = defaultdict(list)
_redis_for_rl: Optional[redis.Redis] = None


def is_rate_limited(key: str, max_calls: int = 8, window_sec: int = 60) -> bool:
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
            return int(results[1] or 0) >= max_calls
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
        return f"ERROR: AI timed out after {_AI_TIMEOUT:.0f}s."
    except Exception as e:
        logger.error("AI pool error: %s", e)
        return f"ERROR: {e}"



def make_cache_key(tool: str, question: str, is_pro: bool) -> str:
    q = " ".join((question or "").lower().split())
    raw = f"{tool}|{1 if is_pro else 0}|{q}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def create_razorpay_order(uid: str, amount_inr: int) -> dict:
    if not config.RAZORPAY_KEY_ID or not config.RAZORPAY_KEY_SECRET:
        return {"error": "Razorpay keys missing"}
    try:
        auth = base64.b64encode(
            f"{config.RAZORPAY_KEY_ID}:{config.RAZORPAY_KEY_SECRET}".encode()
        ).decode()
        payload = {
            "amount": int(amount_inr) * 100,
            "currency": "INR",
            "receipt": f"sg_{str(uid)[:20]}_{int(time.time())}"[:40],
            "notes": {"user_id": str(uid)},
        }
        r = requests.post(
            "https://api.razorpay.com/v1/orders",
            json=payload,
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
            timeout=20,
        )
        data = r.json()
        if r.status_code >= 400:
            logger.error("Razorpay order error: %s", data)
            return {"error": data.get("error", {}).get("description", "Order failed")}
        return data
    except Exception as e:
        logger.error("create_razorpay_order: %s", e)
        return {"error": str(e)}


# ============================================================================
# DATABASE
# ============================================================================

class Database:
    def __init__(self) -> None:
        self.redis = self._connect()
        self._quota_script = None
        if self.redis:
            try:
                self._quota_script = self.redis.register_script(self._QUOTA_LUA)
            except Exception as e:
                logger.warning("Quota Lua script registration failed, will retry per-call: %s", e)

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

    def ensure_user(self, uid: str | int, username: str = "", full_name: str = "", platform: str = "telegram", referred_by: str = "") -> Dict[str, str]:
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
            "badges": "[]",
            "referral_code": secrets.token_hex(4).upper(),
            "referred_by": "",
            "referral_count": "0",
            "last_activity": _today_ist(),
            "created_at": _today_ist(),
        }
        self.save_user(uid, data)
        if self.redis:
            try:
                self.redis.sadd("stats:users", str(uid))
            except Exception:
                pass
        # Register this user's own referral code immediately so anyone can
        # refer them from the moment they exist — regardless of which
        # platform (Telegram/Web/WhatsApp) created the account.
        self.register_referral_code(uid, data["referral_code"])
        if referred_by:
            self.apply_referral(uid, referred_by)
        return self.get_user(uid) or data

    def apply_referral(self, new_uid: str | int, ref_code: str) -> bool:
        """Reward both the new user and the referrer with bonus free questions / XP.
        Zero-cost growth lever — no ads budget needed, existing users bring new ones."""
        if not self.redis or not ref_code:
            return False
        ref_code = ref_code.strip().upper()
        new_uid = str(new_uid)
        try:
            lock_key = f"reflock:{new_uid}"
            if not self.redis.set(lock_key, "1", nx=True, ex=86400):
                return False  # already processed for this user
            referrer_uid = self.redis.get(f"refcode:{ref_code}")
            if not referrer_uid or referrer_uid == new_uid:
                return False
            new_user = self.get_user(new_uid)
            if not new_user or new_user.get("referred_by"):
                return False
            new_user["referred_by"] = referrer_uid
            self.save_user(new_uid, new_user)
            # Bonus: +2 lifetime questions for the new user (soft, capped)
            today = _today_ist()
            self.redis.decrby(f"quota:lifetime:{new_uid}", 2)
            ref_user = self.get_user(referrer_uid)
            if ref_user:
                count = int(ref_user.get("referral_count", 0) or 0) + 1
                ref_user["referral_count"] = str(count)
                self.save_user(referrer_uid, ref_user)
                self.add_xp(referrer_uid, 50)
                # Every 5 successful referrals -> 3 free Pro days
                if count % 5 == 0:
                    self.activate_pro(referrer_uid, days=3)
            return True
        except Exception as e:
            logger.warning("apply_referral: %s", e)
            return False

    def register_referral_code(self, uid: str | int, code: str) -> None:
        if not self.redis or not code:
            return
        try:
            self.redis.set(f"refcode:{code.strip().upper()}", str(uid))
        except Exception:
            pass

    def track_activity(self, uid: str | int) -> None:
        if not self.redis:
            return
        try:
            today = _today_ist()
            uid = str(uid)
            pipe = self.redis.pipeline()
            pipe.sadd(f"dau:{today}", uid)
            pipe.expire(f"dau:{today}", 90000)
            pipe.setex(f"live:{uid}", 120, "1")
            pipe.execute()
        except Exception as e:
            logger.warning("track_activity: %s", e)

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
        # If already pro and not expired, extend from current expiry instead of overwriting
        base = _now_ist()
        try:
            existing_until = user.get("pro_until", "")
            if existing_until:
                existing_dt = datetime.fromisoformat(existing_until)
                if existing_dt > base:
                    base = existing_dt
        except Exception:
            pass
        until = (base + timedelta(days=days)).isoformat()
        user["plan"] = "pro"
        user["pro_until"] = until
        ok = self.save_user(uid, user)
        if ok and self.redis:
            try:
                self.redis.sadd("stats:pro_users", str(uid))
            except Exception:
                pass
        return ok

    def add_xp(self, uid: str | int, amount: int) -> Tuple[int, int]:
        """Atomically add XP and return (total_xp, level)."""
        uid = str(uid)
        amount = int(amount or 0)
        if amount == 0:
            user = self.get_user(uid) or {}
            xp = int(user.get("xp", 0) or 0)
            return xp, (xp // 100) + 1
        # Ensure user hash exists first
        self.ensure_user(uid)
        if self.redis:
            try:
                key = self._key(uid)
                pipe = self.redis.pipeline()
                pipe.hincrby(key, "xp", amount)
                pipe.hget(key, "xp")
                pipe.expire(key, 86400 * 120)
                results = pipe.execute()
                xp = int(results[1] or 0)
                level = (xp // 100) + 1
                self.redis.hset(key, "level", str(level))
                try:
                    self.redis.zadd("leaderboard", {uid: xp})
                except Exception:
                    pass
                return xp, level
            except Exception as e:
                logger.warning("add_xp redis: %s", e)
        # Fallback without redis atomic
        user = self.get_user(uid) or self.ensure_user(uid)
        xp = int(user.get("xp", 0) or 0) + amount
        level = (xp // 100) + 1
        user["xp"] = str(xp)
        user["level"] = str(level)
        self.save_user(uid, user)
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

    # ------------------------------------------------------------------
    # QUOTA — now atomic via Lua script to remove the check-then-consume
    # race condition (two concurrent requests could previously both pass
    # the check before either incremented the counter).
    # ------------------------------------------------------------------
    _QUOTA_LUA = """
    local daily_key = KEYS[1]
    local life_key = KEYS[2]
    local daily_limit = tonumber(ARGV[1])
    local life_limit = tonumber(ARGV[2])
    local daily_ttl = tonumber(ARGV[3])

    local daily_used = tonumber(redis.call('GET', daily_key) or '0')
    local life_used = tonumber(redis.call('GET', life_key) or '0')

    if daily_used >= daily_limit or life_used >= life_limit then
        local daily_left = daily_limit - daily_used
        local life_left = life_limit - life_used
        if daily_left < 0 then daily_left = 0 end
        if life_left < 0 then life_left = 0 end
        return {0, daily_left, life_left}
    end

    daily_used = redis.call('INCR', daily_key)
    redis.call('EXPIRE', daily_key, daily_ttl)
    life_used = redis.call('INCR', life_key)

    local daily_left = daily_limit - daily_used
    local life_left = life_limit - life_used
    if daily_left < 0 then daily_left = 0 end
    if life_left < 0 then life_left = 0 end
    return {1, daily_left, life_left}
    """

    def try_consume_quota(self, uid: str | int) -> Tuple[bool, Dict[str, int]]:
        """Atomically check AND consume in one Redis round trip. Returns
        (allowed, {daily_left, lifetime_left}). Pro users always allowed."""
        if self.is_pro(uid):
            return True, {"daily_left": -1, "lifetime_left": -1}
        if not self.redis:
            return True, {"daily_left": config.FREE_DAILY, "lifetime_left": config.FREE_LIFETIME}
        try:
            today = _today_ist()
            script = self._quota_script or self.redis.register_script(self._QUOTA_LUA)
            allowed, daily_left, life_left = script(
                keys=[f"quota:daily:{uid}:{today}", f"quota:lifetime:{uid}"],
                args=[config.FREE_DAILY, config.FREE_LIFETIME, 90000],
            )
            return bool(int(allowed)), {"daily_left": int(daily_left), "lifetime_left": int(life_left)}
        except Exception as e:
            logger.warning("try_consume_quota: %s", e)
            return True, {"daily_left": config.FREE_DAILY, "lifetime_left": config.FREE_LIFETIME}

    def check_quota(self, uid: str | int) -> Tuple[bool, Dict[str, int]]:
        """Read-only peek at quota (does NOT consume). Used for display only."""
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

    def cache_get(self, key: str) -> Optional[str]:
        if not self.redis or not key:
            return None
        try:
            return self.redis.get(f"ans:{key}")
        except Exception:
            return None

    def cache_set(self, key: str, answer: str, ttl: int = None) -> None:
        if not self.redis or not key or not answer:
            return
        try:
            self.redis.setex(f"ans:{key}", int(ttl or config.CACHE_TTL), answer)
        except Exception:
            pass

    def get_stats(self) -> Dict[str, int]:
        if not self.redis:
            return {"total_users": 0, "total_questions": 0, "dau_today": 0, "pro_users": 0, "live_approx": 0}
        try:
            today = _today_ist()
            live_count = 0
            try:
                cursor = 0
                while True:
                    cursor, keys = self.redis.scan(cursor=cursor, match="live:*", count=100)
                    live_count += len(keys)
                    if cursor == 0:
                        break
            except Exception:
                pass
            return {
                "total_users": int(self.redis.scard("stats:users") or 0),
                "total_questions": int(self.redis.get("stats:total_questions") or 0),
                "dau_today": int(self.redis.scard(f"dau:{today}") or 0),
                "pro_users": int(self.redis.scard("stats:pro_users") or 0),
                "live_approx": live_count,
            }
        except Exception:
            return {"total_users": 0, "total_questions": 0, "dau_today": 0, "pro_users": 0, "live_approx": 0}


db = Database()
_redis_for_rl = db.redis


# ============================================================================
# AI SERVICE
# ============================================================================

class AIService:
    def __init__(self) -> None:
        self.gemini_client = None
        self.groq_client = None
        self.deepseek_ready = bool(config.DEEPSEEK_API_KEY)
        self.openrouter_ready = bool(config.OPENROUTER_API_KEY and config.OPENROUTER_MODELS)
        if config.GOOGLE_API_KEY:
            try:
                self.gemini_client = genai.Client(api_key=config.GOOGLE_API_KEY)
                logger.info("Gemini ready")
            except Exception as e:
                logger.error("Gemini init: %s", e)
        if config.GROQ_API_KEY:
            try:
                self.groq_client = Groq(api_key=config.GROQ_API_KEY)
                logger.info("Groq ready | %s", config.GROQ_MODEL)
            except Exception as e:
                logger.error("Groq init: %s", e)
        if self.deepseek_ready:
            logger.info("DeepSeek ready | %s", config.DEEPSEEK_MODEL)
        if self.openrouter_ready:
            logger.info("OpenRouter ready | %s", config.OPENROUTER_MODELS)

    def _base_prompt(self, is_pro: bool) -> str:
        base = (
            "You are StudyGenie by Sparsh Singhal – India's fun gamified AI tutor for Class 6-12, "
            "JEE, NEET, GATE, UPSC, SSC, Banking, CA, CUET, Olympiads. Reply in natural Hinglish. "
            "Be clear, exam-oriented, encouraging, use emojis. "
            "Use clean Markdown: headings, bold, bullet lists, and simple tables when helpful. ""For math use LaTeX in \\( ... \\) or $$ ... $$. Also add one plain-English line under hard formulas.\n\n"
        )
        if is_pro:
            base += "PRO user: give deeper explanations, tips, memory tricks, common mistakes, exam strategy.\n\n"
        return base

    def _templates(self, base: str, question: str, is_pro: bool = False) -> Dict[str, str]:
        n_pyq = 20 if is_pro else 10
        n_mock = 15 if is_pro else 10
        return {
            "general": (
                f"{base}"
                "Tool=GENERAL. Answer the student's question helpfully.\n"
                "Do not force a special format unless asked.\n\n"
                f"Student:\n{question}"
            ),
            "explain": (
                f"{base}"
                "Tool=EXPLAIN only. Explain the concept simply with analogy + examples.\n"
                "Do NOT give a full study plan, mock test, or only formula list.\n\n"
                f"Topic/Question:\n{question}"
            ),
            "solve": (
                f"{base}"
                "Tool=SOLVE only. Solve step-by-step. Show working. Box final answer.\n"
                "If input is only a topic (not a problem), ask for the exact problem OR give 1 worked example.\n\n"
                f"Problem:\n{question}"
            ),
            "notes": (
                f"{base}"
                "Tool=NOTES only. Short exam-ready notes: bullets, key points, formulas.\n"
                "No 7-day plan. No full mock test.\n\n"
                f"Topic:\n{question}"
            ),
            "pyq": (
                f"{base}"
                "Tool=PYQ only.\n"
                "User message may be (1) a full past question to solve, or (2) a topic with optional filters.\n"
                "If full question: solve step-by-step with tips and common mistakes.\n"
                f"If topic: generate exactly {n_pyq} exam-style questions STRICTLY on that topic.\n"
                "TOPIC FILTER: stay on topic; match exam style if named (JEE/NEET/GATE/SSC/DTU).\n"
                "PREVIOUS YEAR TRENDS: 4-6 bullets before questions (frequent ideas, weightage feel). Never invent paper codes.\n"
                "Mix: objective only / subjective only / default BOTH (half-half).\n"
                "Format: Trends → Numbered questions → Answer key.\n\n"
                f"User input:\n{question}"
            ),
            "formula": (
                f"{base}"
                "Tool=FORMULA only. List important formulas with short notes.\n"
                "Put each formula in $$ ... $$. One plain-English line under each.\n"
                "No full theory chapter. No mock test.\n\n"
                f"Topic:\n{question}"
            ),
            "planner": (
                f"{base}"
                "Tool=PLANNER only. Output ONLY a day-wise study timetable, NOT notes/guide.\n"
                "Default 7 days unless user says otherwise.\n"
                "Markdown table: Day | Focus | Tasks | Duration | Outcome.\n"
                "End with weekly hours + progress tips.\n"
                "FORBIDDEN: long theory, definitions-only guide, pipeline explanation without schedule.\n\n"
                f"User request:\n{question}"
            ),
            "mock": (
                f"{base}"
                "Tool=MOCK TEST only.\n"
                f"Create a timed-style mock: exactly {n_mock} questions on the given topic/subject.\n"
                "Structure:\n"
                "1) Exam header (topic, marks, suggested time)\n"
                "2) Questions numbered (mix MCQ + short if useful)\n"
                "3) Do NOT reveal answers until after a clear separator line 'ANSWER KEY'\n"
                "4) Answer key with brief explanations\n"
                "FORBIDDEN: teaching notes or chapter summary instead of a test.\n"
                "If user only says a broad subject (e.g. physics), pick a high-yield subtopic set and still make a mock.\n\n"
                f"Topic:\n{question}"
            ),
            "roast": (
                f"{base}"
                "Tool=ROAST. Hinglish savage but educational roast while teaching the concept.\n\n"
                f"Doubt:\n{question}"
            ),
            "ncert": (
                f"{base}"
                "Tool=NCERT style. Clear textbook-like explanation.\n\n"
                f"Topic:\n{question}"
            ),
            "mindmap": (
                f"{base}"
                "Tool=MINDMAP only. Hierarchical text mind-map (branches). No long paragraphs.\n\n"
                f"Topic:\n{question}"
            ),
            "important": (
                f"{base}"
                "Tool=IMPORTANT Qs. 10-12 high-yield questions with short answers.\n\n"
                f"Topic:\n{question}"
            ),
            "diagram": (
                f"{base}"
                "Tool=DIAGRAM explain. Describe/explain diagram for exams.\n\n"
                f"Input:\n{question}"
            ),
            "derivation": (
                f"{base}"
                "Tool=DERIVATION only. Full step-by-step derivation.\n\n"
                f"Derive:\n{question}"
            ),
            "numerical": (
                f"{base}"
                "Tool=NUMERICAL only. Formula, substitution, final answer with units.\n\n"
                f"Problem:\n{question}"
            ),
            "mcq": (
                f"{base}"
                "Tool=MCQ GENERATOR only. 8 MCQs (easy-medium-hard) with answers.\n"
                "Not a full syllabus notes dump.\n\n"
                f"Topic:\n{question}"
            ),
            "essay": (
                f"{base}"
                "Tool=ESSAY/LETTER. Well-structured formal writing as requested.\n\n"
                f"Request:\n{question}"
            ),
            "resume": (
                f"{base}"
                "Tool=RESUME. Clean ATS-friendly student resume content.\n\n"
                f"Details:\n{question}"
            ),
            "youtube": (
                f"{base}"
                "Tool=YOUTUBE summary style + 5 revision questions.\n\n"
                f"Topic:\n{question}"
            ),
            "career": (
                f"{base}"
                "Tool=CAREER guidance for Indian students.\n\n"
                f"Question:\n{question}"
            ),
            "tips": (
                f"{base}"
                "Tool=STUDY TIPS only.\n\n"
                f"Request:\n{question}"
            ),
            "ocr": (
                f"{base}"
                "Tool=OCR. Read the image and solve/explain.\n\n"
                f"Extra:\n{question}"
            ),
        }


    def _call_groq(self, prompt: str, max_tokens: int = 1500) -> Optional[str]:
        if not self.groq_client:
            return None
        try:
            resp = self.groq_client.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": "You are StudyGenie. Reply in Hinglish. Use clean Markdown."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=max_tokens,
            )
            text = (resp.choices[0].message.content or "").strip()
            return text or None
        except Exception as e:
            logger.error("Groq: %s", e)
            return None

    def _call_gemini(self, prompt: str, max_tokens: int = 1500, model: Optional[str] = None) -> Optional[str]:
        if not self.gemini_client:
            return None
        try:
            resp = self.gemini_client.models.generate_content(
                model=model or config.GEMINI_MODEL,
                contents=prompt,
                config=genai_types.GenerateContentConfig(temperature=0.7, max_output_tokens=max_tokens),
            )
            text = (resp.text or "").strip()
            return text or None
        except Exception as e:
            logger.error("Gemini (%s): %s", model or config.GEMINI_MODEL, e)
            return None

    def _call_gemini_flash_lite(self, prompt: str, max_tokens: int = 1500) -> Optional[str]:
        return self._call_gemini(prompt, max_tokens=max_tokens, model=config.GEMINI_FLASH_LITE_MODEL)

    def _call_openai_compatible(self, base_url: str, api_key: str, model: str, prompt: str,
                                 max_tokens: int, extra_headers: Optional[Dict[str, str]] = None,
                                 timeout: int = 30) -> Optional[str]:
        """Shared helper for any OpenAI-compatible chat/completions endpoint
        (DeepSeek, OpenRouter, etc.) — avoids pulling in the openai SDK
        just for two providers when `requests` already does the job."""
        try:
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            if extra_headers:
                headers.update(extra_headers)
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are StudyGenie. Reply in Hinglish. Use clean Markdown."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.7,
                "max_tokens": max_tokens,
            }
            r = requests.post(f"{base_url.rstrip('/')}/chat/completions", json=payload, headers=headers, timeout=timeout)
            if r.status_code >= 400:
                logger.error("%s HTTP %s: %s", model, r.status_code, r.text[:300])
                return None
            data = r.json()
            text = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
            return text or None
        except Exception as e:
            logger.error("OpenAI-compatible call (%s): %s", model, e)
            return None

    def _call_deepseek(self, prompt: str, max_tokens: int = 1500) -> Optional[str]:
        if not config.DEEPSEEK_API_KEY:
            return None
        return self._call_openai_compatible(
            config.DEEPSEEK_BASE_URL, config.DEEPSEEK_API_KEY, config.DEEPSEEK_MODEL,
            prompt, max_tokens,
        )

    def _call_openrouter(self, prompt: str, max_tokens: int = 1500) -> Optional[str]:
        if not config.OPENROUTER_API_KEY or not config.OPENROUTER_MODELS:
            return None
        headers = {
            "HTTP-Referer": config.OPENROUTER_SITE_URL,
            "X-Title": config.OPENROUTER_APP_NAME,
        }
        # Rotate through the free-model list so one saturated/rate-limited
        # model doesn't take the whole fallback chain down with it.
        for model in config.OPENROUTER_MODELS:
            text = self._call_openai_compatible(
                "https://openrouter.ai/api/v1", config.OPENROUTER_API_KEY, model,
                prompt, max_tokens, extra_headers=headers,
            )
            if text:
                return text
        return None

    def answer(self, question: str, tool: str = "general", is_pro: bool = False) -> Optional[str]:
        if not question or not question.strip():
            return "Please ask a valid question."
        base = self._base_prompt(is_pro)
        templates = self._templates(base, question.strip(), is_pro=is_pro)
        prompt = templates.get(tool, templates["general"])
        max_tokens = 2800 if (is_pro and tool == "pyq") else (2000 if is_pro else (1800 if tool == "pyq" else 1400))
        # 4-provider reliability chain: Groq -> DeepSeek -> Gemini Flash-Lite
        # -> OpenRouter (free models). Each is skipped instantly if its key
        # isn't configured, so this degrades gracefully to whatever subset
        # of providers you've actually set up.
        providers = [
            ("groq", self._call_groq),
            ("deepseek", self._call_deepseek),
            ("gemini_flash_lite", self._call_gemini_flash_lite),
            ("openrouter", self._call_openrouter),
        ]
        # Retry the whole chain once more if every provider fails on the
        # first pass (handles transient blips without giving up too soon).
        for attempt in range(2):
            for name, fn in providers:
                text = fn(prompt, max_tokens=max_tokens)
                if text:
                    if attempt > 0 or name != "groq":
                        logger.info("Answer served by fallback provider: %s", name)
                    return text
            if attempt == 0:
                time.sleep(1.2)
        return None

    def answer_with_image(self, img_bytes: bytes, mime: str, question: str = "", tool: str = "ocr", is_pro: bool = False) -> Optional[str]:
        if not self.gemini_client:
            return "Image understanding unavailable right now."
        base = self._base_prompt(is_pro)
        prompt = f"{base}Look at the image and solve/explain. Extra: {question or 'Explain fully'}"
        try:
            resp = self.gemini_client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=[genai_types.Part.from_bytes(data=img_bytes, mime_type=mime or "image/jpeg"), prompt],
                config=genai_types.GenerateContentConfig(temperature=0.4, max_output_tokens=1800),
            )
            return (resp.text or "").strip() or None
        except Exception as e:
            logger.error("Vision: %s", e)
            return None


ai = AIService()


def get_ai_answer(question: str, tool: str, is_pro: bool) -> Optional[str]:
    """Single entry point used by ALL surfaces (Telegram/WhatsApp/Web) so
    caching is consistent everywhere instead of duplicated ad-hoc per route."""
    ckey = make_cache_key(tool, question, is_pro)
    cached = db.cache_get(ckey)
    if cached:
        return cached
    text = run_ai(ai.answer, question, tool, is_pro=is_pro)
    if text and not str(text).startswith("ERROR:"):
        db.cache_set(ckey, text)
        return text
    return None


# ============================================================================
# TELEGRAM (same as before)
# ============================================================================

async def typing(update: Update) -> None:
    try:
        if update.effective_chat:
            await update.effective_chat.send_action(ChatAction.TYPING)
    except Exception:
        pass


async def reply(update: Update, text: str, reply_markup=None) -> None:
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        elif update.message:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        try:
            if update.message:
                await update.message.reply_text(text, reply_markup=reply_markup)
        except Exception:
            pass


def main_menu(is_pro: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📚 Ask Doubt", callback_data="menu_ask"),
         InlineKeyboardButton("🛠 Tools", callback_data="menu_tools")],
        [InlineKeyboardButton("📊 Progress", callback_data="menu_progress"),
         InlineKeyboardButton("🏆 Leaderboard", callback_data="menu_lb")],
        [InlineKeyboardButton("🔥 Streak", callback_data="menu_streak"),
         InlineKeyboardButton("🎁 Refer & Earn", callback_data="menu_refer")],
    ]
    if is_pro:
        rows.append([InlineKeyboardButton("👑 You are PRO", callback_data="menu_prostatus")])
    else:
        rows.append([InlineKeyboardButton(f"💎 Upgrade ₹{config.PRO_PRICE_INR}", callback_data="menu_upgrade")])
    rows.append([InlineKeyboardButton("👨‍💻 About Sparsh Singhal", callback_data="menu_about")])
    return InlineKeyboardMarkup(rows)


def tools_menu(is_pro: bool = False) -> InlineKeyboardMarkup:
    tools = [
        ("explain", "📖 Explain"), ("solve", "🧮 Solve"), ("notes", "📝 Notes"),
        ("pyq", "📜 PYQ"), ("formula", "📐 Formula"), ("planner", "📅 Planner"),
    ]
    if is_pro:
        # Full parity with the web sidebar — every Pro tool that exists
        # must be reachable here, not just the ones that happened to get
        # added first.
        tools += [
            ("mock", "🎯 Mock"), ("roast", "🔥 Roast"), ("mindmap", "🧠 Mindmap"),
            ("mcq", "❓ MCQ"), ("ncert", "📘 NCERT"), ("derivation", "📐 Derivation"),
            ("numerical", "🔢 Numerical"), ("essay", "✍️ Essay"), ("resume", "📄 Resume"),
            ("career", "🚀 Career"), ("tips", "💡 Tips"), ("important", "⭐ Important Qs"),
            ("diagram", "🧬 Diagram"), ("youtube", "📺 YouTube Notes"),
        ]
    else:
        tools += [("mock", "🎯 Mock 🔒")]
    rows = []
    for i in range(0, len(tools), 2):
        row = [InlineKeyboardButton(tools[i][1], callback_data=f"tool_{tools[i][0]}")]
        if i + 1 < len(tools):
            row.append(InlineKeyboardButton(tools[i + 1][1], callback_data=f"tool_{tools[i + 1][0]}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("« Back", callback_data="menu_main")])
    return InlineKeyboardMarkup(rows)


PRO_ONLY_TOOLS = {"roast", "ncert", "mindmap", "important", "diagram", "derivation", "numerical",
                   "mcq", "essay", "resume", "youtube", "career", "tips", "mock"}

# Keyword prefixes used to auto-detect which tool the user meant when they
# just type free text instead of picking from a menu — shared by Telegram
# and WhatsApp so both surfaces behave identically instead of WhatsApp only
# ever running "general". Every PRO_ONLY_TOOLS entry needs a prefix here too,
# otherwise typing the tool name is the ONLY way in and some tools become
# unreachable if the corresponding menu button is ever missed.
TOOL_KEYWORDS = [
    ("explain", "explain"), ("solve", "solve"), ("notes", "notes"), ("pyq", "pyq"),
    ("formula", "formula"), ("plan", "planner"), ("mock", "mock"), ("roast", "roast"),
    ("mindmap", "mindmap"), ("mcq", "mcq"), ("essay", "essay"), ("resume", "resume"),
    ("career", "career"), ("tips", "tips"), ("ncert", "ncert"), ("derivation", "derivation"),
    ("derive", "derivation"), ("numerical", "numerical"), ("important", "important"),
    ("diagram", "diagram"), ("youtube", "youtube"),
]


def detect_tool_from_text(text: str, default: str = "general") -> str:
    lower = (text or "").lower()
    for key, name in TOOL_KEYWORDS:
        if lower.startswith(key):
            return name
    return default


async def process_question(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, tool: str = "general") -> None:
    user = update.effective_user
    if not user:
        return
    uid = user.id
    is_pro = db.is_pro(uid)
    db.track_activity(uid)
    if tool in PRO_ONLY_TOOLS and not is_pro:
        await reply(update, f"🔒 Pro-only tool.\n\nUpgrade ₹{config.PRO_PRICE_INR}/30 days.",
                    InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade", callback_data="menu_upgrade")]]))
        return
    if not is_pro:
        can, quota = db.try_consume_quota(uid)
        if not can:
            await reply(update, f"❌ Free quota finished!\nDaily: {quota['daily_left']} | Lifetime: {quota['lifetime_left']}\n\nUpgrade for unlimited access 💎")
            return
    await typing(update)
    start = time.time()
    answer = get_ai_answer(text, tool, is_pro)
    elapsed = time.time() - start
    if not answer:
        await reply(update, "😔 Answer generate nahi ho paya abhi. Please dobara try karo 30 seconds baad.")
        return
    udata = db.ensure_user(uid, user.username or "", user.full_name or "Student")
    xp_gain = config.XP_QUESTION * (2 if is_pro else 1)
    xp, level = db.add_xp(uid, xp_gain)
    try:
        if db.redis:
            db.redis.hincrby(db._key(uid), "questions_asked", 1)
            db.redis.incr("stats:total_questions")
    except Exception:
        pass
    db.update_streak(uid)
    footer = f"\n\n━━━━━━━━━━━━━━━\n⚡ {elapsed:.1f}s | ⭐ +{xp_gain} XP{' (2× Pro)' if is_pro else ''} | Level {level}\n_ - made with love by Sparsh Singhal _"
    full = answer + footer
    if len(full) <= 4096:
        await reply(update, full)
    else:
        for i, chunk in enumerate([full[j:j + 4000] for j in range(0, len(full), 4000)]):
            if i == 0:
                await reply(update, chunk)
            elif update.message:
                await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    ref_code = ""
    if context.args:
        arg0 = context.args[0]
        if arg0.startswith("ref_"):
            ref_code = arg0[4:]
    udata = db.ensure_user(user.id, user.username or "", user.full_name or "Student", referred_by=ref_code)
    db.register_referral_code(user.id, udata.get("referral_code", ""))
    db.track_activity(user.id)
    bonus_note = "\n\n🎁 Referral bonus applied!" if ref_code else ""
    await reply(update,
                f"🎓 *Welcome to StudyGenie!*\n\nHi {user.first_name}! Type your doubt or use menu.{bonus_note}\n\n_ - made with love by Sparsh Singhal _",
                main_menu(db.is_pro(user.id)))


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await reply(update, "🏠 *Main Menu*", main_menu(db.is_pro(user.id) if user else False))


async def free_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if not text:
        return
    uid = update.effective_user.id if update.effective_user else 0
    # Explicit tool selection (via /Tools menu) wins; otherwise auto-detect
    # from the message text itself using the same keyword logic WhatsApp uses.
    tool = db.pop_tool(uid) or detect_tool_from_text(text)
    await process_question(update, context, text, tool)


async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    u = db.ensure_user(user.id)
    xp = int(u.get("xp", 0))
    level = int(u.get("level", 1))
    await reply(update, f"📊 *Progress*\n\n⭐ Level {level}\nXP: {xp}\n🔥 Streak: {u.get('streak', 0)}\n📚 Questions: {u.get('questions_asked', 0)}")


async def streak_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    s = db.update_streak(user.id)
    await reply(update, f"🔥 *Streak*\nCurrent: {s['current']} | Best: {s['best']} | Shields: {s['shields']}")


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    board = db.get_leaderboard(15)
    if not board:
        await reply(update, "🏆 Empty leaderboard. Be first!")
        return
    lines = ["🏆 *Leaderboard*\n"]
    for e in board:
        m = {1: "🥇", 2: "🥈", 3: "🥉"}.get(e["rank"], f"{e['rank']}.")
        lines.append(f"{m} {e['name']} – L{e['level']} ({e['xp']} XP)")
    rank = db.get_rank(update.effective_user.id)
    if rank:
        lines.append(f"\n📍 Your rank: #{rank}")
    await reply(update, "\n".join(lines))


async def refer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    udata = db.ensure_user(user.id, user.username or "", user.full_name or "Student")
    code = udata.get("referral_code", "")
    db.register_referral_code(user.id, code)
    bot_username = context.bot.username if context.bot else "StudyGenieBot"
    link = f"https://t.me/{bot_username}?start=ref_{code}"
    count = udata.get("referral_count", "0")
    await reply(update,
                f"🎁 *Refer & Earn – StudyGenie by Sparsh Singhal*\n\n"
                f"Apna link doston ko bhejo:\n{link}\n\n"
                f"✅ Har referral pe +50 XP\n✅ Har 5 referral pe 3 din FREE Pro\n\n"
                f"👥 Total referrals: {count}")


async def upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    uid = user.id if user else 0
    domain = config.VERCEL_URL.rstrip("/") if config.VERCEL_URL else "studygenie-by-sparsh-singhal.onrender.com"
    link = f"https://{domain}/pay?uid={uid}"
    await reply(update,
                f"💎 *StudyGenie Pro – ₹{config.PRO_PRICE_INR}/30 days*\n\n"
                "Unlimited • Roast • Mindmap • OCR • 2× XP\n\n"
                f"Pay here: {link}\n\n_ - made with love by Sparsh Singhal _")


async def about_sparsh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reply(update, "👨‍💻 *Sparsh Singhal*\n\nCreator & Developer of StudyGenie 🎓\nBuilt with ❤️ for Indian students — gamified learning for every exam.\n\n_StudyGenie — by Sparsh Singhal_")


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""
    user = update.effective_user
    uid = user.id if user else 0
    is_pro = db.is_pro(uid)
    if data == "menu_main":
        await menu(update, context)
    elif data == "menu_ask":
        await reply(update, "📚 Type your question now.")
    elif data == "menu_tools":
        await reply(update, "🛠 *Tools*", tools_menu(is_pro))
    elif data == "menu_progress":
        await progress(update, context)
    elif data == "menu_lb":
        await leaderboard(update, context)
    elif data == "menu_streak":
        await streak_cmd(update, context)
    elif data == "menu_refer":
        await refer_cmd(update, context)
    elif data == "menu_upgrade":
        await upgrade(update, context)
    elif data == "menu_about":
        await about_sparsh(update, context)
    elif data == "menu_prostatus":
        await reply(update, "👑 You are PRO. Enjoy unlimited power!")
    elif data.startswith("tool_"):
        tool = data.replace("tool_", "")
        if tool in PRO_ONLY_TOOLS and not is_pro:
            await reply(update, f"🔒 Pro-only tool.\n\nUpgrade ₹{config.PRO_PRICE_INR}/30 days.",
                        InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade", callback_data="menu_upgrade")]]))
            return
        db.set_tool(uid, tool)
        await reply(update, f"✅ Tool: *{tool}*\nAb sawaal type karo.")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.message or not update.message.photo:
        return
    uid = user.id
    db.track_activity(uid)
    if not db.is_pro(uid):
        await reply(update, f"📷 Image OCR is Pro-only. Upgrade ₹{config.PRO_PRICE_INR}.",
                    InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade", callback_data="menu_upgrade")]]))
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
            await reply(update, "😔 Could not read image.")
            return
        udata = db.ensure_user(uid, user.username or "", user.full_name or "Student")
        xp_gain = config.XP_QUESTION * 2
        xp, level = db.add_xp(uid, xp_gain)
        try:
            if db.redis:
                db.redis.hincrby(db._key(uid), "questions_asked", 1)
        except Exception:
            pass
        footer = f"\n\n━━━━━━━━━━━━━━━\n📷 OCR | ⚡ {elapsed:.1f}s | ⭐ +{xp_gain} XP (2× Pro) | Level {level}"
        await reply(update, answer + footer)
    except Exception as e:
        logger.exception("Photo: %s", e)
        await reply(update, "😔 Image error.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Error: %s", context.error)


telegram_app: Optional[Application] = None
_lock = asyncio.Lock()


async def get_app() -> Application:
    global telegram_app
    if telegram_app:
        return telegram_app
    async with _lock:
        if telegram_app:
            return telegram_app
        app_ = (
            ApplicationBuilder()
            .token(config.BOT_TOKEN)
            .defaults(Defaults(parse_mode=ParseMode.MARKDOWN))
            .build()
        )
        app_.add_handler(CommandHandler("start", start))
        app_.add_handler(CommandHandler("menu", menu))
        app_.add_handler(CommandHandler("progress", progress))
        app_.add_handler(CommandHandler("streak", streak_cmd))
        app_.add_handler(CommandHandler("leaderboard", leaderboard))
        app_.add_handler(CommandHandler("refer", refer_cmd))
        app_.add_handler(CommandHandler("upgrade", upgrade))
        app_.add_handler(CommandHandler("about", about_sparsh))
        app_.add_handler(CallbackQueryHandler(callback))
        app_.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        app_.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, free_text))
        app_.add_error_handler(error_handler)
        await app_.initialize()
        telegram_app = app_
        return app_


def process_whatsapp_message(from_number: str, text: str, profile_name: str = "") -> None:
    uid = f"wa:{from_number}"
    db.ensure_user(uid, full_name=profile_name or "WhatsApp Student", platform="whatsapp")
    db.track_activity(uid)
    is_pro = db.is_pro(uid)
    tool = detect_tool_from_text(text)
    if tool in PRO_ONLY_TOOLS and not is_pro:
        _send_whatsapp_text(from_number, f"🔒 Pro-only tool.\n\nUpgrade ₹{config.PRO_PRICE_INR}/30 days — StudyGenie by Sparsh Singhal.")
        return
    if not is_pro:
        can, quota = db.try_consume_quota(uid)
        if not can:
            _send_whatsapp_text(from_number, f"❌ Free quota finished!\nDaily: {quota['daily_left']} | Lifetime: {quota['lifetime_left']}\n\nUpgrade for unlimited access 💎")
            return
    answer = get_ai_answer(text, tool, is_pro)
    if not answer:
        _send_whatsapp_text(from_number, "😔 Abhi answer generate nahi ho paya. Please 30 second baad dobara try karo.")
        return
    db.update_streak(uid)
    xp, level = db.add_xp(uid, config.XP_QUESTION * (2 if is_pro else 1))
    if db.redis:
        try:
            db.redis.hincrby(db._key(uid), "questions_asked", 1)
            db.redis.incr("stats:total_questions")
        except Exception:
            pass
    footer = f"\n\n━━━━━━━━━━━━━━━\n⭐ +{config.XP_QUESTION * (2 if is_pro else 1)} XP{' (2× Pro)' if is_pro else ''} | Level {level}\n- made with love by Sparsh Singhal"
    _send_whatsapp_text(from_number, answer + footer)


def _send_whatsapp_text(to_number: str, body: str) -> None:
    if config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_NUMBER_ID:
        try:
            url = f"https://graph.facebook.com/{config.WHATSAPP_API_VERSION}/{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
            headers = {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}", "Content-Type": "application/json"}
            requests.post(url, json={"messaging_product": "whatsapp", "to": to_number, "type": "text",
                                     "text": {"body": body[:4000]}}, headers=headers, timeout=15)
        except Exception as e:
            logger.error("WA send: %s", e)


# ============================================================================
# FRONTEND with Markdown renderer
# ============================================================================

FRONTEND_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css" crossorigin="anonymous">
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js" crossorigin="anonymous"></script>
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js" crossorigin="anonymous"></script>

<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>StudyGenie by Sparsh Singhal</title>
<meta name="description" content="StudyGenie — India's gamified AI tutor, built by Sparsh Singhal.">
<style>
:root{--bg:#0b1220;--card:#111827;--accent:#22d3ee;--text:#f1f5f9;--muted:#94a3b8;--border:rgba(255,255,255,0.08)}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex;flex-direction:column}
header{background:linear-gradient(90deg,#0f172a,#1e1b4b);padding:.85rem 1.25rem;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--border);position:sticky;top:0;z-index:50}
.logo-wrap{display:flex;align-items:center;gap:.65rem;cursor:pointer;user-select:none}
.logo-wrap img{width:36px;height:36px;border-radius:50%;object-fit:cover;border:2px solid var(--accent)}
.logo{font-size:1.25rem;font-weight:700}.logo span{color:var(--accent)}
.brand-sub{font-size:.7rem;color:var(--muted);margin-top:1px}
.stats{font-size:.82rem;color:var(--muted);display:flex;gap:1rem;align-items:center;flex-wrap:wrap}
.pro-btn-top{background:linear-gradient(90deg,#a78bfa,#ec4899);color:#fff;border:none;border-radius:999px;padding:.35rem .85rem;font-size:.78rem;font-weight:700;cursor:pointer}
main{flex:1;display:grid;grid-template-columns:280px 1fr;max-width:1400px;margin:0 auto;width:100%}
@media(max-width:900px){main{grid-template-columns:1fr}.sidebar{display:none}}
.sidebar{background:var(--card);border-right:1px solid var(--border);padding:1.25rem 1rem;overflow-y:auto}
.sidebar h3{font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:1rem 0 .6rem}
.tool-btn{display:block;width:100%;text-align:left;background:transparent;border:1px solid transparent;color:var(--text);padding:.55rem .8rem;border-radius:8px;margin-bottom:.25rem;cursor:pointer;font-size:.92rem}
.tool-btn:hover,.tool-btn.active{background:rgba(34,211,238,.12);border-color:var(--accent);color:var(--accent)}
.pro-badge{background:linear-gradient(90deg,#a78bfa,#ec4899);color:#fff;font-size:.65rem;padding:.12rem .4rem;border-radius:999px;margin-left:.35rem}
.pay-side{display:block;width:100%;margin:1rem 0 .5rem;background:linear-gradient(90deg,#a78bfa,#ec4899);color:#fff;border:none;border-radius:10px;padding:.7rem;font-weight:700;cursor:pointer;font-size:.9rem}
.creator-card{display:flex;gap:.7rem;align-items:center;padding:.75rem;background:#0f172a;border-radius:12px;border:1px solid var(--border);margin-bottom:1rem}
.creator-card img{width:48px;height:48px;border-radius:50%;object-fit:cover;border:2px solid var(--accent)}
.creator-card .name{font-weight:700;font-size:.9rem}
.creator-card .role{font-size:.72rem;color:var(--muted)}
.refer-side{display:block;width:100%;margin:.5rem 0;background:#0f172a;border:1px solid var(--accent);color:var(--accent);border-radius:10px;padding:.6rem;font-weight:700;cursor:pointer;font-size:.85rem}
.chat-area{display:flex;flex-direction:column;height:calc(100vh - 64px)}
.messages{flex:1;overflow-y:auto;padding:1.25rem;display:flex;flex-direction:column;gap:1rem}
.msg{max-width:88%;padding:.95rem 1.1rem;border-radius:16px;line-height:1.6;word-break:break-word}
.msg.user{align-self:flex-end;background:linear-gradient(135deg,#0891b2,#0e7490);border-bottom-right-radius:4px;white-space:pre-wrap}
.msg.bot{align-self:flex-start;background:var(--card);border:1px solid var(--border);border-bottom-left-radius:4px}
.msg.bot h1,.msg.bot h2,.msg.bot h3,.msg.bot h4{color:#f1f5f9;margin:.7rem 0 .35rem;line-height:1.3}
.msg.bot h1{font-size:1.2rem}.msg.bot h2{font-size:1.1rem}.msg.bot h3{font-size:1.02rem}
.msg.bot p{margin:.35rem 0}
.msg.bot ul,.msg.bot ol{margin:.4rem 0 .4rem 1.25rem}
.msg.bot li{margin:.2rem 0}
.msg.bot table{border-collapse:collapse;width:100%;font-size:.88rem;margin:.55rem 0}
.msg.bot th,.msg.bot td{border:1px solid var(--border);padding:.4rem .55rem;text-align:left}
.msg.bot th{background:#0f172a}
.msg.bot code{background:#0f172a;padding:.1rem .35rem;border-radius:4px;font-size:.88em}
.msg.bot pre{background:#0f172a;padding:.75rem;border-radius:8px;overflow:auto;margin:.5rem 0}
.msg.bot hr{border:none;border-top:1px solid var(--border);margin:.75rem 0}
.msg .meta{font-size:.72rem;color:var(--muted);margin-top:.55rem}
.input-area{padding:1rem 1.25rem 1.25rem;background:var(--card);border-top:1px solid var(--border)}
.input-row{display:flex;gap:.65rem;align-items:flex-end}
textarea{flex:1;background:#0f172a;border:1px solid var(--border);border-radius:12px;color:var(--text);padding:.85rem 1rem;resize:none;font-size:1rem;min-height:48px;outline:none}
button.send{background:var(--accent);color:#0b1220;border:none;border-radius:12px;padding:0 1.25rem;height:48px;font-weight:700;cursor:pointer}
button.send:disabled{opacity:.5}
.tools-bar{display:flex;gap:.45rem;margin-bottom:.65rem;flex-wrap:wrap}
.tools-bar select,.tools-bar button{background:#0f172a;border:1px solid var(--border);color:var(--text);padding:.35rem .7rem;border-radius:8px;font-size:.82rem}
.welcome{text-align:center;padding:2.5rem 1rem;color:var(--muted)}
.welcome img{width:72px;height:72px;border-radius:50%;object-fit:cover;border:3px solid var(--accent);margin-bottom:.75rem}
.welcome h2{color:var(--text);margin-bottom:.35rem}
.lb-item{display:flex;justify-content:space-between;padding:.4rem 0;font-size:.88rem;border-bottom:1px solid var(--border)}
.loading{opacity:.85;font-style:italic}
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.65);display:none;align-items:center;justify-content:center;z-index:100;padding:1rem}
.modal-bg.show{display:flex}
.modal{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:1.5rem;max-width:420px;width:100%;max-height:90vh;overflow-y:auto}
.modal h2{margin-bottom:.5rem;font-size:1.2rem}
.modal ul{margin:1rem 0;padding-left:1.1rem;color:var(--muted);line-height:1.75;font-size:.92rem}
.modal .price{font-size:1.6rem;color:var(--accent);font-weight:700;margin:.5rem 0}
.modal .actions{display:flex;gap:.5rem;margin-top:1rem}
.modal .actions button{flex:1;padding:.7rem;border:none;border-radius:10px;font-weight:700;cursor:pointer}
.btn-pro{background:linear-gradient(90deg,#a78bfa,#ec4899);color:#fff}
.btn-close{background:#0f172a;color:var(--text);border:1px solid var(--border)!important}
input.name-input{width:100%;padding:.7rem;margin:1rem 0;border-radius:8px;border:1px solid var(--border);background:#0f172a;color:var(--text);font-size:1rem}
footer.brand-footer{text-align:center;padding:.5rem;font-size:.72rem;color:var(--muted);border-top:1px solid var(--border);background:var(--card)}
footer.brand-footer strong{color:var(--accent)}
</style>
</head>
<body>
<header>
  <div class="logo-wrap" id="logoClick" title="StudyGenie">
    <img src="/sparsh.jpg" alt="Sparsh Singhal" onerror="this.style.display='none'">
    <div>
      <div class="logo">Study<span>Genie</span></div>
      <div class="brand-sub">by Sparsh Singhal</div>
    </div>
  </div>
  <div class="stats">
    <span id="name-display" style="cursor:pointer;color:var(--accent);position:relative;z-index:50;pointer-events:auto" onclick="openNameModal()" title="Change name">👤 Set name</span>
    <span id="xp-display">⭐ 0 XP</span>
    <span id="level-display">Level 1</span>
    <span id="quota-display">Free</span>
    <button class="pro-btn-top" onclick="openProModal()">💎 Pro</button>
  </div>
</header>
<main>
  <aside class="sidebar">
    <div class="creator-card">
      <img src="/sparsh.jpg" alt="Sparsh Singhal" onerror="this.style.display='none'">
      <div>
        <div class="name">Sparsh Singhal</div>
        <div class="role">Creator of StudyGenie</div>
      </div>
    </div>
    <h3>Tools</h3>
    <button class="tool-btn active" data-tool="general">💬 General Ask</button>
    <button class="tool-btn" data-tool="explain">📖 Explain</button>
    <button class="tool-btn" data-tool="solve">🧮 Solve</button>
    <button class="tool-btn" data-tool="notes">📝 Notes</button>
    <button class="tool-btn" data-tool="pyq">📜 PYQ</button>
    <button class="tool-btn" data-tool="formula">📐 Formula</button>
    <button class="tool-btn" data-tool="planner">📅 Planner</button>
    <button class="tool-btn" data-tool="mock">🎯 Mock Test <span class="pro-badge">PRO</span></button>
    <button class="tool-btn" data-tool="roast">🔥 Roast <span class="pro-badge">PRO</span></button>
    <button class="tool-btn" data-tool="mindmap">🧠 Mind Map <span class="pro-badge">PRO</span></button>
    <button class="tool-btn" data-tool="mcq">❓ MCQ Generator <span class="pro-badge">PRO</span></button>
    <button class="tool-btn" data-tool="ncert">📘 NCERT Style <span class="pro-badge">PRO</span></button>
    <button class="tool-btn" data-tool="derivation">📐 Derivation <span class="pro-badge">PRO</span></button>
    <button class="tool-btn" data-tool="numerical">🔢 Numerical <span class="pro-badge">PRO</span></button>
    <button class="tool-btn" data-tool="essay">✍️ Essay / Letter <span class="pro-badge">PRO</span></button>
    <button class="tool-btn" data-tool="resume">📄 Resume <span class="pro-badge">PRO</span></button>
    <button class="tool-btn" data-tool="career">🚀 Career Guide <span class="pro-badge">PRO</span></button>
    <button class="tool-btn" data-tool="tips">💡 Sparsh Tips <span class="pro-badge">PRO</span></button>
    <button class="tool-btn" data-tool="important">⭐ Important Qs <span class="pro-badge">PRO</span></button>
    <button class="tool-btn" data-tool="diagram">🧬 Diagram Explain <span class="pro-badge">PRO</span></button>
    <button class="tool-btn" data-tool="youtube">📺 YouTube Notes <span class="pro-badge">PRO</span></button>
    <button class="pay-side" onclick="openProModal()">🔫 Ammo khatam. Please upgrade to PRO – ₹{{ price }} for 30 days</button>
    <button class="refer-side" onclick="openReferModal()">🎁 Refer & Earn Free Pro</button>
    <h3>🏆 Live Leaderboard</h3>
    <div id="lb-list">Loading...</div>
  </aside>
  <section class="chat-area">
    <div class="messages" id="messages">
      <div class="welcome">
        <img src="/sparsh.jpg" alt="Sparsh Singhal" onerror="this.style.display='none'">
        <h2>Welcome to StudyGenie 🎓</h2>
        <p>Built with ❤️ by <strong>Sparsh Singhal</strong></p>
        <p style="margin-top:.75rem;font-size:.9rem">All exams • Free tools + Pro power</p>
      </div>
    </div>
    <div class="input-area">
      <div class="tools-bar">
        <select id="toolSelect">
          <option value="general">General</option>
          <option value="explain">Explain</option>
          <option value="solve">Solve</option>
          <option value="notes">Notes</option>
          <option value="pyq">PYQ</option>
          <option value="formula">Formula</option>
          <option value="planner">Planner</option>
          <option value="mock">Mock (Pro)</option>
          <option value="roast">Roast (Pro)</option>
          <option value="mindmap">Mindmap (Pro)</option>
          <option value="mcq">MCQ (Pro)</option>
          <option value="ncert">NCERT (Pro)</option>
          <option value="derivation">Derivation (Pro)</option>
          <option value="numerical">Numerical (Pro)</option>
          <option value="essay">Essay (Pro)</option>
          <option value="resume">Resume (Pro)</option>
          <option value="career">Career (Pro)</option>
          <option value="tips">Tips (Pro)</option>
          <option value="important">Important Qs (Pro)</option>
          <option value="diagram">Diagram (Pro)</option>
          <option value="youtube">YouTube Notes (Pro)</option>
        </select>
        <button onclick="onImageButtonClick()">📷 Image</button>
        <input type="file" id="imageInput" accept="image/*" style="display:none" onchange="handleImage(this)">
      </div>
      <div class="input-row">
        <textarea id="question" placeholder="Dimaag mein kya ghoom raha hai? Poocho... 🔥" rows="1"></textarea>
        <button class="send" id="sendBtn" onclick="ask()">🔥 Fire</button>
      </div>
    </div>
  </section>
</main>
<footer class="brand-footer">🎓 StudyGenie — built with ❤️ by <strong>Sparsh Singhal</strong></footer>

<div class="modal-bg" id="proModal">
  <div class="modal">
    <h2>💎 StudyGenie Pro</h2>
    <div class="price">₹{{ price }} <span style="font-size:1rem;color:var(--muted)">/ 30 days</span></div>
    <ul>
      <li>Unlimited questions</li>
      <li>🔥 Roast • 🧠 Mind Maps • ❓ MCQ • 🎯 Mock Tests</li>
      <li>📘 NCERT • 📐 Derivation • 🔢 Numerical</li>
      <li>📷 Image OCR • ✍️ Essay • 📄 Resume</li>
      <li>⭐ Important Qs • 🧬 Diagram • 📺 YouTube Notes</li>
      <li>🚀 Career • 💡 Tips • ⭐ 2× XP</li>
    </ul>
    <div class="actions">
      <button class="btn-pro" onclick="goPay()">Pay & Unlock Pro</button>
      <button class="btn-close" onclick="closeProModal()">Close</button>
    </div>
  </div>
</div>

<div class="modal-bg" id="referModal">
  <div class="modal">
    <h2>🎁 Refer & Earn — by Sparsh Singhal</h2>
    <p style="color:var(--muted);font-size:.9rem;margin-top:.4rem">Apna referral link doston ko bhejo:</p>
    <input id="referLinkBox" class="name-input" type="text" readonly />
    <ul style="margin-top:.75rem">
      <li>Har referral pe +50 XP</li>
      <li>Har 5 referral pe 3 din FREE Pro</li>
    </ul>
    <div class="actions">
      <button class="btn-pro" onclick="copyReferLink()">Copy Link</button>
      <button class="btn-close" onclick="closeReferModal()">Close</button>
    </div>
    <p id="referMsg" style="margin-top:.6rem;font-size:.85rem;color:var(--muted)"></p>
  </div>
</div>

<div class="modal-bg" id="devModal">
  <div class="modal">
    <h2>🔐 Developer Mode</h2>
    <p style="color:var(--muted);font-size:.9rem">Enter secret code</p>
    <input id="devCode" type="password" placeholder="Secret code" class="name-input" />
    <div class="actions">
      <button class="btn-pro" onclick="checkDev()">Unlock</button>
      <button class="btn-close" onclick="closeDevModal()">Close</button>
    </div>
    <p id="devMsg" style="margin-top:.75rem;font-size:.85rem;color:var(--muted)"></p>
  </div>
</div>

<div class="modal-bg" id="nameModal">
  <div class="modal">
    <h2>👤 Apna naam likho</h2>
    <p style="color:var(--muted);font-size:.9rem;margin-top:.4rem">Yeh naam leaderboard pe dikhega</p>
    <input id="nameInput" class="name-input" type="text" maxlength="40" placeholder="e.g. Rahul Sharma" />
    <div class="actions">
      <button class="btn-pro" onclick="saveName()">Save</button>
      <button class="btn-close" onclick="closeNameModal()">Skip</button>
    </div>
    <p id="nameMsg" style="margin-top:.6rem;font-size:.85rem;color:var(--muted)"></p>
  </div>
</div>

<script>
const PRICE = {{ price }};
let currentTool = "general";
let referCode = "";

// --- Pro upgrade modal — these were referenced by onclick= handlers above
// but never implemented, so the main monetization button did nothing at all.
function openProModal(){
  const m = document.getElementById("proModal");
  if(!m) return;
  m.classList.add("show");
  try{ soundClick(); }catch(e){}
}
function closeProModal(){
  const m = document.getElementById("proModal");
  if(m) m.classList.remove("show");
}
function goPay(){
  try{ soundClick(); }catch(e){}
  window.location.href = "/pay?uid=" + encodeURIComponent("web:" + clientId);
}

// --- Hidden Dev Mode — tap the logo 5× within 3 seconds to open it.
// (devModal already existed in the HTML but had no way to open it.)
function openDevModal(){
  const m = document.getElementById("devModal");
  if(!m) return;
  m.classList.add("show");
  try{ soundClick(); }catch(e){}
}
function closeDevModal(){
  const m = document.getElementById("devModal");
  if(m) m.classList.remove("show");
}
async function checkDev(){
  const codeInput = document.getElementById("devCode");
  const msg = document.getElementById("devMsg");
  const code = (codeInput && codeInput.value || "").trim();
  if(!code){
    if(msg){ msg.style.color = "#f87171"; msg.textContent = "Enter a code."; }
    return;
  }
  try{
    const res = await fetch("/api/dev/activate-pro", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ code, uid: "web:" + clientId })
    });
    const data = await res.json();
    if(data.ok){
      if(msg){ msg.style.color = "#22d3ee"; msg.textContent = "✅ Pro activated for testing!"; }
      isProUser = true;
      syncProfile();
      try{ soundRecv(); }catch(e){}
      setTimeout(closeDevModal, 700);
    }else{
      if(msg){ msg.style.color = "#f87171"; msg.textContent = data.error || "Invalid code."; }
      try{ soundError(); }catch(e){}
    }
  }catch(e){
    if(msg){ msg.style.color = "#f87171"; msg.textContent = "Network error"; }
  }
}

function openReferModal(){
  const m = document.getElementById("referModal");
  if(!m) return;
  m.classList.add("show");
  fetch("/api/me?client_id=" + encodeURIComponent(clientId)).then(r=>r.json()).then(data=>{
    if(data.ok && data.referral_code){
      referCode = data.referral_code;
      const box = document.getElementById("referLinkBox");
      if(box) box.value = window.location.origin + "/?ref=" + referCode;
    }
  });
  try{ soundClick(); }catch(e){}
}
function closeReferModal(){
  const m = document.getElementById("referModal");
  if(m) m.classList.remove("show");
}
function copyReferLink(){
  const box = document.getElementById("referLinkBox");
  const msg = document.getElementById("referMsg");
  if(!box || !box.value) return;
  box.select();
  try{
    navigator.clipboard.writeText(box.value);
    if(msg){ msg.style.color="#22d3ee"; msg.textContent = "Copied! Share karo doston ke saath."; }
    soundRecv();
  }catch(e){
    if(msg) msg.textContent = "Copy manually.";
  }
}

function onImageButtonClick(){
  if(!isProUser){
    try{ soundError(); }catch(e){}
    alert("Only for pro plan users");
    return;
  }
  const el = document.getElementById("imageInput");
  if(el) el.click();
}
function handleImage(input){
  // Free users: block immediately with popup
  if(!isProUser){
    try{ soundError(); }catch(e){}
    alert("Only for pro plan users");
    try{ input.value = ""; }catch(e){}
    imageBase64 = null;
    return;
  }
  const file = input && input.files && input.files[0];
  if(!file){
    try{ soundError(); }catch(e){}
    addMessage("bot", "No image selected.");
    return;
  }
  if(!file.type || !file.type.startsWith("image/")){
    try{ soundError(); }catch(e){}
    addMessage("bot", "Please choose an image file (JPG/PNG/WebP).");
    return;
  }
  if(file.size > 4.5 * 1024 * 1024){
    try{ soundError(); }catch(e){}
    addMessage("bot", "Image too large. Please use under ~4MB.");
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    try{
      const dataUrl = String(reader.result || "");
      const parts = dataUrl.split(",");
      imageBase64 = parts.length > 1 ? parts[1] : "";
      if(!imageBase64){
        addMessage("bot", "Could not read image.");
        return;
      }
      window._imageMime = file.type || "image/jpeg";
      addMessage("user", "📷 Image ready: " + (file.name || "photo") + " — ab question likho (optional) aur 🔥 Fire dabao");
      try{ soundClick(); }catch(e){}
    }catch(err){
      addMessage("bot", "Image read failed.");
    }
  };
  reader.onerror = () => {
    addMessage("bot", "Image read error.");
    try{ soundError(); }catch(e){}
  };
  reader.readAsDataURL(file);
  try{ input.value = ""; }catch(e){}
}

function openNameModal(){
  const m = document.getElementById("nameModal");
  if(!m) return;
  m.classList.add("show");
  const input = document.getElementById("nameInput");
  const cur = (document.getElementById("name-display")||{}).textContent || "";
  if(input && cur && !cur.includes("Set name")){
    input.value = cur.replace(/^👤\s*/, "").trim();
  }
  setTimeout(() => { try{ input && input.focus(); }catch(e){} }, 50);
  try{ soundClick(); }catch(e){}
}
function closeNameModal(){
  const m = document.getElementById("nameModal");
  if(m) m.classList.remove("show");
  try{ localStorage.setItem("sg_name_skipped", "1"); }catch(e){}
}
async function saveName(){
  const input = document.getElementById("nameInput");
  const msg = document.getElementById("nameMsg");
  const name = (input && input.value || "").trim();
  if(!name || name.length < 2){
    if(msg){ msg.style.color = "#f87171"; msg.textContent = "Naam kam se kam 2 letters ka ho"; }
    try{ soundError(); }catch(e){}
    return;
  }
  try{
    const res = await fetch("/api/set-name", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ client_id: clientId, name })
    });
    const data = await res.json();
    if(data.ok){
      const el = document.getElementById("name-display");
      if(el) el.textContent = "👤 " + data.name;
      try{ localStorage.setItem("sg_name", data.name); }catch(e){}
      if(msg){ msg.style.color = "#22d3ee"; msg.textContent = "Saved!"; }
      try{ soundRecv(); }catch(e){}
      setTimeout(closeNameModal, 400);
    }else{
      if(msg){ msg.style.color = "#f87171"; msg.textContent = data.error || "Failed"; }
      try{ soundError(); }catch(e){}
    }
  }catch(e){
    if(msg){ msg.style.color = "#f87171"; msg.textContent = "Network error"; }
    try{ soundError(); }catch(e){}
  }
}
// restore saved name in header
(function(){
  try{
    const saved = localStorage.getItem("sg_name");
    if(saved){
      const el = document.getElementById("name-display");
      if(el) el.textContent = "👤 " + saved;
    }
  }catch(e){}
})();


async function syncProfile(){
  try{
    const params = new URLSearchParams(window.location.search);
    const refFromUrl = params.get("ref") || "";
    const url = "/api/me?client_id=" + encodeURIComponent(clientId) + (refFromUrl ? "&ref=" + encodeURIComponent(refFromUrl) : "");
    const res = await fetch(url);
    const data = await res.json();
    if(!data.ok) return;
    if(data.name && data.name !== "Web Student" && data.name !== "Student"){
      const el = document.getElementById("name-display");
      if(el) el.textContent = "👤 " + data.name;
    }
    if(data.xp !== undefined){
      const x = document.getElementById("xp-display");
      if(x) x.textContent = `⭐ ${data.xp} XP`;
    }
    if(data.level !== undefined){
      const l = document.getElementById("level-display");
      if(l) l.textContent = `Level ${data.level}`;
    }
    if(data.plan === "pro" || (data.quota && data.quota.daily_left === -1)){
      isProUser = true;
    } else {
      isProUser = false;
    }
    if(data.quota){
      const q = document.getElementById("quota-display");
      if(q) q.textContent = data.quota.daily_left === -1 ? "PRO ∞" : `Free: ${data.quota.daily_left} left`;
    }
  }catch(e){}
}
syncProfile();

const TOOL_PLACEHOLDERS = {
  general: "Dimaag mein kya ghoom raha hai? Poocho... 🔥",
  explain: "Konsa concept bhoot ban gaya hai samajh mein? 👻",
  solve: "Problem yahan daalo, sulja denge 💪",
  notes: "Last-minute revision? Topic bolo, notes ready 📝",
  pyq: "Purana paper khodna hai? Topic bata, khazana milega 🕵️",
  formula: "Formula bhool gaye? Koi na, yahan maang lo 📐",
  planner: "Aalas chhodo, ab plan banate hain 📅",
  mock: "Ready ho jao — asli exam jaisa mahaul milega 🎯",
  roast: "Dimaag lagao, warna pyaar se roast ho jaoge 🔥😂",
  mindmap: "Topic do, branches khud ugengi 🧠🌳",
  mcq: "Options mein ghoomte ho? Practice yahan karo ❓",
  ncert: "Seedhi-saadi NCERT wali baat chahiye? Yahan bolo 📘",
  derivation: "Formula aaya kahan se? Chalo jadd tak jaate hain 📐✨",
  numerical: "Number crunching time! Problem daalo yahan 🔢",
  essay: "Shabdon ka jaadu chahiye? Topic bolo, likh dete hain ✍️",
  resume: "Apna CV chamkaate hain — details daalo 📄✨",
  career: "Future ka confusion? Befikar poocho 🚀",
  tips: "Sparsh bhaiya ke secret tips chahiye? Bolo 💡",
  important: "100% exam mein aane wale sawaal chahiye? Bolo ⭐",
  diagram: "Diagram dekh ke ghabraya mat, samjha dete hain 🧬",
  youtube: "Lecture dekhne ka time nahi? Summary yahan lo 📺",
};

function setTool(tool){
  if(!tool) return;
  currentTool = tool;
  document.querySelectorAll(".tool-btn").forEach(b => {
    b.classList.toggle("active", b.getAttribute("data-tool") === tool);
  });
  const sel = document.getElementById("toolSelect");
  if(sel){
    // if option missing, keep value anyway
    sel.value = tool;
  }
  const qBox = document.getElementById("question");
  if(qBox){
    qBox.placeholder = TOOL_PLACEHOLDERS[tool] || TOOL_PLACEHOLDERS.general;
  }
  try{ soundClick(); }catch(e){}
}
document.querySelectorAll(".tool-btn").forEach(btn => {
  btn.addEventListener("click", () => setTool(btn.getAttribute("data-tool")));
});
const _toolSelect = document.getElementById("toolSelect");
if(_toolSelect){
  _toolSelect.addEventListener("change", () => setTool(_toolSelect.value));
}

let clientId = localStorage.getItem("sg_client") || ("web_" + Math.random().toString(36).slice(2));
localStorage.setItem("sg_client", clientId);
let imageBase64 = null;
let isProUser = false;
let logoClicks = 0;
let logoTimer = null;
const _logoEl = document.getElementById("logoClick");
if(_logoEl){
  _logoEl.addEventListener("click", () => {
    logoClicks++;
    if(logoTimer) clearTimeout(logoTimer);
    logoTimer = setTimeout(() => { logoClicks = 0; }, 3000);
    if(logoClicks >= 5){
      logoClicks = 0;
      openDevModal();
    }
  });
}

const AudioCtx = window.AudioContext || window.webkitAudioContext;
let actx = null;
function beep(freq, dur, type="square", vol=0.35){
  try{
    if(!actx) actx = new AudioCtx();
    if(actx.state === "suspended") actx.resume();
    const o = actx.createOscillator();
    const g = actx.createGain();
    o.type = type;
    o.frequency.value = freq;
    g.gain.value = vol;
    o.connect(g); g.connect(actx.destination);
    o.start();
    g.gain.exponentialRampToValueAtTime(0.001, actx.currentTime + dur);
    o.stop(actx.currentTime + dur);
  }catch(e){}
}
function soundSend(){ beep(180, 0.06, "sawtooth", 0.4); setTimeout(()=>beep(90, 0.12, "square", 0.35), 40); }
function soundRecv(){ beep(520, 0.05, "square", 0.3); setTimeout(()=>beep(780, 0.08, "square", 0.35), 60); setTimeout(()=>beep(1040, 0.1, "triangle", 0.3), 140); }
function soundClick(){ beep(240, 0.04, "square", 0.28); }
function soundError(){ beep(120, 0.15, "sawtooth", 0.4); setTimeout(()=>beep(80, 0.2, "sawtooth", 0.35), 100); }

function escapeHtml(s){
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function mdToHtml(text){
  if(!text) return "";
  const slots = [];
  // Protect math blocks before HTML escape / markdown
  let s = String(text).replace(/\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$[^$\n]+\$/g, function(m){
    slots.push(m);
    return "%%MATH" + (slots.length - 1) + "%%";
  });
  s = escapeHtml(s);

  s = s.replace(/```([\s\S]*?)```/g, function(_, code){
    return "<pre><code>" + code.trim() + "</code></pre>";
  });
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");

  s = s.replace(/^######\s+(.*)$/gm, "<h6>$1</h6>");
  s = s.replace(/^#####\s+(.*)$/gm, "<h5>$1</h5>");
  s = s.replace(/^####\s+(.*)$/gm, "<h4>$1</h4>");
  s = s.replace(/^###\s+(.*)$/gm, "<h3>$1</h3>");
  s = s.replace(/^##\s+(.*)$/gm, "<h2>$1</h2>");
  s = s.replace(/^#\s+(.*)$/gm, "<h1>$1</h1>");

  s = s.replace(/\*\*\*([^*]+)\*\*\*/g, "<strong><em>$1</em></strong>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/\*([^*]+)\*/g, "<em>$1</em>");

  // tables
  s = s.replace(/(?:^|\n)((?:\|.+\|(?:\n|$))+)/g, function(_, block){
    const rows = block.trim().split("\n").filter(Boolean);
    if(rows.length < 1) return block;
    let html = "<div style='overflow:auto'><table>";
    let headerDone = false;
    rows.forEach((row) => {
      if(/^\|?\s*[-:| ]+\s*\|?$/.test(row)) return;
      const cells = row.replace(/^\|/, "").replace(/\|$/, "").split("|").map(c => c.trim());
      if(!headerDone){
        html += "<thead><tr>" + cells.map(c => "<th>" + c + "</th>").join("") + "</tr></thead><tbody>";
        headerDone = true;
      } else {
        html += "<tr>" + cells.map(c => "<td>" + c + "</td>").join("") + "</tr>";
      }
    });
    html += "</tbody></table></div>";
    return "\n" + html + "\n";
  });

  s = s.replace(/^\s*[-*]\s+(.*)$/gm, "<li>$1</li>");
  s = s.replace(/(?:<li>.*<\/li>\s*)+/g, function(m){ return "<ul>" + m + "</ul>"; });
  s = s.replace(/^\s*\d+\.\s+(.*)$/gm, "<li>$1</li>");

  s = s.replace(/\n{2,}/g, "</p><p>");
  s = s.replace(/\n/g, "<br>");
  s = "<p>" + s + "</p>";
  s = s.replace(/<p>\s*<\/p>/g, "");
  s = s.replace(/<p>\s*(<h[1-6]>)/g, "$1");
  s = s.replace(/(<\/h[1-6]>)\s*<\/p>/g, "$1");
  s = s.replace(/<p>\s*(<ul>)/g, "$1");
  s = s.replace(/(<\/ul>)\s*<\/p>/g, "$1");
  s = s.replace(/<p>\s*(<div)/g, "$1");
  s = s.replace(/(<\/div>)\s*<\/p>/g, "$1");
  s = s.replace(/<p>\s*(<pre>)/g, "$1");
  s = s.replace(/(<\/pre>)\s*<\/p>/g, "$1");

  // Restore math (unescaped LaTeX for KaTeX)
  s = s.replace(/%%MATH(\d+)%%/g, function(_, i){
    return slots[parseInt(i, 10)] || "";
  });
  return s;
}

function renderMsgMath(el){
  if(!el) return;
  const run = () => {
    if(!window.renderMathInElement) return false;
    try{
      renderMathInElement(el, {
        delimiters: [
          {left: "$$", right: "$$", display: true},
          {left: "\\[", right: "\\]", display: true},
          {left: "$", right: "$", display: false},
          {left: "\\(", right: "\\)", display: false}
        ],
        throwOnError: false,
        ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code"]
      });
      return true;
    }catch(e){ return false; }
  };
  if(run()) return;
  let tries = 0;
  const t = setInterval(() => {
    tries++;
    if(run() || tries > 20) clearInterval(t);
  }, 100);
}
function addMessage(role, text, meta=""){
  const div = document.createElement("div");
  div.className = "msg " + role;
  const body = (role === "bot") ? mdToHtml(text) : escapeHtml(text).replace(/\n/g,"<br>");
  div.innerHTML = body + (meta ? `<div class="meta">${escapeHtml(meta)}</div>` : "");
  const box = document.getElementById("messages");
  const welcome = box.querySelector(".welcome");
  if(welcome) welcome.remove();
  box.appendChild(div);
  if(role === "bot") renderMsgMath(div);
  box.scrollTop = box.scrollHeight;
}

async function ask(){
  const sel = document.getElementById("toolSelect");
  if(sel && sel.value) currentTool = sel.value;
  const q = document.getElementById("question").value.trim();
  if(!q && !imageBase64) return;
  const btn = document.getElementById("sendBtn");
  btn.disabled = true; btn.textContent = "...";
  soundSend();
  addMessage("user", q || "📷 Image question");
  document.getElementById("question").value = "";
  const loading = document.createElement("div");
  loading.className = "msg bot loading";
  loading.textContent = "🎯 Target locked by Sparsh Singhal's StudyGenie...";
  document.getElementById("messages").appendChild(loading);
  try{
    const res = await fetch("/api/webask", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ question: q, tool: currentTool, client_id: clientId, image_base64: imageBase64 || undefined, image_mime: window._imageMime || "image/jpeg" })
    });
    const data = await res.json();
    loading.remove();
    addMessage("bot", data.answer || "No response", data.elapsed ? `⚡ ${data.elapsed}s` : "");
    soundRecv();
    if(data.xp !== undefined && data.xp !== null){
      document.getElementById("xp-display").textContent = `⭐ ${data.xp} XP`;
      if(data.level !== undefined) document.getElementById("level-display").textContent = `Level ${data.level}`;
    } else {
      syncProfile();
    }
    if(data.quota){
      const qq = data.quota;
      isProUser = (qq.daily_left === -1);
      document.getElementById("quota-display").textContent = qq.daily_left === -1 ? "PRO ∞" : `Free: ${qq.daily_left} left`;
    }
  }catch(err){
    loading.remove();
    addMessage("bot", "😔 Network error. Please try again.");
    soundError();
  }
  imageBase64 = null;
  btn.disabled = false; btn.textContent = "🔥 Fire";
}

document.getElementById("question").addEventListener("keydown", e=>{
  if(e.key === "Enter" && !e.shiftKey){ e.preventDefault(); ask(); }
});

async function loadLB(){
  try{
    const res = await fetch("/api/leaderboard");
    const data = await res.json();
    const list = document.getElementById("lb-list");
    if(!data.board || !data.board.length){
      list.innerHTML = "<div style='color:#64748b;font-size:.85rem'>No one yet</div>";
      return;
    }
    list.innerHTML = data.board.slice(0,8).map(e=>
      `<div class="lb-item"><span>${e.rank}. ${e.name}</span><span>L${e.level}</span></div>`
    ).join("");
  }catch{}
}
loadLB();
setInterval(loadLB, 30000);
</script>
</body>
</html>
"""

PAY_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Upgrade Pro – StudyGenie by Sparsh Singhal</title>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
<style>
body{font-family:system-ui,sans-serif;background:#0b1220;color:#f1f5f9;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}
.card{background:#111827;border:1px solid rgba(255,255,255,.08);border-radius:16px;padding:2rem;max-width:420px;width:90%;text-align:center}
h1{font-size:1.4rem;margin:0 0 .5rem}
.price{font-size:2rem;color:#22d3ee;font-weight:700;margin:1rem 0}
ul{text-align:left;color:#94a3b8;line-height:1.7}
button{background:#22d3ee;color:#0b1220;border:none;border-radius:12px;padding:.9rem 1.5rem;font-weight:700;width:100%;margin-top:1.2rem;cursor:pointer}
button:disabled{opacity:.5}
.msg{margin-top:1rem;font-size:.9rem;color:#94a3b8}
a{color:#22d3ee}
.creator{display:flex;align-items:center;gap:.6rem;justify-content:center;margin-top:1rem;font-size:.8rem;color:#94a3b8}
.creator img{width:28px;height:28px;border-radius:50%;object-fit:cover;border:1px solid #22d3ee}
</style>
</head>
<body>
<div class="card">
  <h1>🎓 StudyGenie Pro</h1>
  <p>Unlimited doubts • Roast • Mindmap • OCR • 2× XP</p>
  <div class="price">₹{{ price }} <span style="font-size:1rem;color:#94a3b8">/ 30 days</span></div>
  <ul>
    <li>Unlimited questions</li>
    <li>All Pro tools unlocked</li>
    <li>Image OCR</li>
    <li>2× XP + priority</li>
  </ul>
  <button id="payBtn" onclick="startPay()">Pay ₹{{ price }} Securely</button>
  <p class="msg" id="status">User: {{ uid }}</p>
  <p class="msg"><a href="/">← Back to StudyGenie</a></p>
  <div class="creator"><img src="/sparsh.jpg" alt="Sparsh Singhal" onerror="this.style.display='none'"> Built by Sparsh Singhal</div>
</div>
<script>
const UID={{ uid|tojson }};
const KEY_ID={{ key_id|tojson }};
async function startPay(){
  const btn=document.getElementById("payBtn");
  const status=document.getElementById("status");
  btn.disabled=true;status.textContent="Creating order...";
  try{
    const res=await fetch("/api/create-order",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({uid:UID})});
    const data=await res.json();
    if(data.error){status.textContent="Error: "+data.error;btn.disabled=false;return;}
    const rzp=new Razorpay({
      key:KEY_ID,amount:data.amount,currency:"INR",name:"StudyGenie Pro",
      description:"30 days Pro",order_id:data.id,notes:{user_id:UID},
      handler:function(){status.textContent="✅ Payment successful! Pro activates shortly."},
      theme:{color:"#22d3ee"},
      modal:{ondismiss:function(){btn.disabled=false;status.textContent="Payment cancelled."}}
    });
    rzp.open();btn.disabled=false;
  }catch(e){status.textContent="Network error";btn.disabled=false;}
}
</script>
</body>
</html>
"""

# ============================================================================
# FLASK
# ============================================================================

app = Flask(__name__)


@app.route("/sparsh.jpg")
def serve_photo():
    try:
        return send_from_directory(".", "sparsh.jpg")
    except Exception:
        return "", 404


@app.route("/")
def home():
    return render_template_string(FRONTEND_HTML, price=config.PRO_PRICE_INR)


@app.route("/pay")
def pay_page():
    uid = (request.args.get("uid") or "").strip()
    if not uid:
        return "Missing uid. Open from Upgrade link.", 400
    if not config.RAZORPAY_KEY_ID:
        return "Payment not configured.", 503
    return render_template_string(
        PAY_HTML, uid=uid, price=config.PRO_PRICE_INR, key_id=config.RAZORPAY_KEY_ID
    )


@app.route("/api/create-order", methods=["POST"])
def api_create_order():
    data = request.get_json(silent=True) or {}
    uid = (data.get("uid") or "").strip()
    if not uid:
        return jsonify({"error": "uid required"}), 400
    order = create_razorpay_order(uid, config.PRO_PRICE_INR)
    if "error" in order:
        return jsonify(order), 400
    return jsonify({"id": order.get("id"), "amount": order.get("amount"), "currency": order.get("currency", "INR")})



@app.route("/api/me")
def api_me():
    client_id = (request.args.get("client_id") or "").strip()
    if not client_id:
        return jsonify({"ok": False, "error": "client_id required"}), 400
    ref = (request.args.get("ref") or "").strip()
    uid = f"web:{client_id}"
    user = db.ensure_user(uid, full_name="Web Student", platform="web", referred_by=ref)
    db.register_referral_code(uid, user.get("referral_code", ""))
    xp = int(user.get("xp", 0) or 0)
    level = int(user.get("level", 1) or 1)
    return jsonify({
        "ok": True,
        "uid": uid,
        "name": user.get("full_name") or "Student",
        "xp": xp,
        "level": level,
        "plan": "pro" if db.is_pro(uid) else "free",
        "quota": db.check_quota(uid)[1],
        "referral_code": user.get("referral_code", ""),
        "referral_count": user.get("referral_count", "0"),
    })

@app.route("/api/set-name", methods=["POST"])
def api_set_name():
    data = request.get_json(silent=True) or {}
    client_id = (data.get("client_id") or "").strip()
    name = (data.get("name") or "").strip()[:40]
    if not client_id:
        return jsonify({"ok": False, "error": "client_id required"}), 400
    if not name or len(name) < 2:
        return jsonify({"ok": False, "error": "Name too short"}), 400
    name = " ".join(name.split())
    uid = f"web:{client_id}"
    udata = db.ensure_user(uid, full_name=name, platform="web")
    udata["full_name"] = name
    db.save_user(uid, udata)
    return jsonify({"ok": True, "name": name})


@app.route("/health")
def health():
    redis_ok = False
    if db.redis:
        try:
            redis_ok = bool(db.redis.ping())
        except Exception:
            pass
    return jsonify({
        "ok": True, "redis": redis_ok,
        "providers": {
            "groq": ai.groq_client is not None,
            "deepseek": ai.deepseek_ready,
            "gemini_flash_lite": ai.gemini_client is not None,
            "openrouter": ai.openrouter_ready,
        },
        "version": "StudyGenie v6.0 (4-Provider Fallback Chain+Referral+Security)",
        "creator": "Sparsh Singhal",
    })


@app.route("/api/debug/ai")
def debug_ai():
    if not config.DEV_SECRET or not hmac.compare_digest(request.args.get("code", ""), config.DEV_SECRET):
        return jsonify({"ok": False}), 403
    results: Dict[str, Any] = {
        "chain_order": ["groq", "deepseek", "gemini_flash_lite", "openrouter"],
        "keys_present": {
            "groq": bool(config.GROQ_API_KEY),
            "deepseek": bool(config.DEEPSEEK_API_KEY),
            "gemini": bool(config.GOOGLE_API_KEY),
            "openrouter": bool(config.OPENROUTER_API_KEY),
        },
    }
    test_prompt = "Say exactly: OK StudyGenie"

    def _timed(fn, *a, **kw):
        t0 = time.time()
        try:
            text = fn(*a, **kw)
            return {"ok": bool(text), "reply": (text or "")[:200], "elapsed": round(time.time() - t0, 2)}
        except Exception as e:
            return {"ok": False, "error": str(e), "elapsed": round(time.time() - t0, 2)}

    if ai.groq_client:
        results["groq"] = {**_timed(ai._call_groq, test_prompt, max_tokens=50), "model": config.GROQ_MODEL}
    else:
        results["groq"] = {"ok": False, "error": "not initialized"}

    if ai.deepseek_ready:
        results["deepseek"] = {**_timed(ai._call_deepseek, test_prompt, max_tokens=50), "model": config.DEEPSEEK_MODEL}
    else:
        results["deepseek"] = {"ok": False, "error": "DEEPSEEK_API_KEY not set"}

    if ai.gemini_client:
        results["gemini_flash_lite"] = {**_timed(ai._call_gemini_flash_lite, test_prompt, max_tokens=50),
                                         "model": config.GEMINI_FLASH_LITE_MODEL}
    else:
        results["gemini_flash_lite"] = {"ok": False, "error": "not initialized"}

    if ai.openrouter_ready:
        results["openrouter"] = {**_timed(ai._call_openrouter, test_prompt, max_tokens=50),
                                  "models_tried": config.OPENROUTER_MODELS}
    else:
        results["openrouter"] = {"ok": False, "error": "OPENROUTER_API_KEY not set"}

    return jsonify(results)


@app.route("/api/webask", methods=["POST"])
def web_ask():
    data = request.get_json(silent=True) or {}
    q = (data.get("question") or "").strip()
    tool = (data.get("tool") or "general").strip().lower()
    client_id = (data.get("client_id") or request.remote_addr or "anon").strip()
    image_b64 = data.get("image_base64") or ""
    if is_rate_limited(f"web:{client_id}", max_calls=8, window_sec=60):
        return jsonify({"answer": "Too many requests. Wait a minute.\n\n- made with love by Sparsh Singhal"}), 429
    if len(image_b64) > 6_500_000:  # ~4.5MB binary -> base64 overhead cap
        return jsonify({"answer": "Image too large. Please use under ~4MB.\n\n- made with love by Sparsh Singhal"}), 400
    if not q and not image_b64:
        return jsonify({"answer": "Please type a question or upload an image"}), 400
    uid = f"web:{client_id}"
    udata = db.ensure_user(uid, full_name="Web Student", platform="web")
    db.track_activity(uid)
    is_pro = db.is_pro(uid)
    if (tool in PRO_ONLY_TOOLS or image_b64) and not is_pro:
        return jsonify({"answer": f"🔒 Pro-only.\n\nUpgrade ₹{config.PRO_PRICE_INR}/30 days.\n\n- made with love by Sparsh Singhal"})
    if not is_pro:
        can, quota = db.try_consume_quota(uid)
        if not can:
            return jsonify({"answer": "❌ Quota finished! Upgrade to Pro for unlimited access.\n\n- made with love by Sparsh Singhal", "quota": quota})
    start = time.time()
    cached = False
    answer = None
    if image_b64:
        try:
            img_bytes = base64.b64decode(image_b64)
            answer = run_ai(ai.answer_with_image, img_bytes, data.get("image_mime", "image/jpeg"), q, "ocr", is_pro)
        except Exception as e:
            logger.error("Image: %s", e)
            answer = "Could not read the image."
    else:
        ckey = make_cache_key(tool, q, is_pro)
        answer = db.cache_get(ckey)
        if answer:
            cached = True
        else:
            answer = run_ai(ai.answer, q, tool, is_pro=is_pro)
            if answer and not str(answer).startswith("ERROR:"):
                db.cache_set(ckey, answer)
    elapsed = time.time() - start
    if not answer or str(answer).startswith("ERROR:"):
        # Friendly, non-leaky message — technical detail stays server-side in logs only.
        logger.warning("AI failure for uid=%s tool=%s reason=%s", uid, tool, answer)
        return jsonify({
            "answer": "😔 Abhi answer generate nahi ho paya. 15-20 second baad phir try karo.\n\n- made with love by Sparsh Singhal"
        })
    if not is_pro:
        pass  # already consumed atomically above via try_consume_quota
    xp_gain = config.XP_QUESTION * (2 if is_pro else 1)
    xp, level = db.add_xp(uid, xp_gain)
    try:
        if db.redis:
            db.redis.hincrby(db._key(uid), "questions_asked", 1)
            db.redis.incr("stats:total_questions")
    except Exception:
        pass
    _, quota = db.check_quota(uid)
    rank = db.get_rank(uid)
    footer = (
        f"\n\n━━━━━━━━━━━━━━━\n"
        f"⚡ {elapsed:.1f}s"
        f"{' | 📦 cache' if cached else ''}"
        f" | 🛠️ {tool}"
        f" | ⭐ +{xp_gain} XP{' (2× Pro)' if is_pro else ''} | Level {level}\n"
        f"- made with love by Sparsh Singhal"
    )
    return jsonify({"answer": answer + footer, "xp": xp, "level": level, "rank": rank, "quota": quota, "elapsed": round(elapsed, 2), "cached": cached})


@app.route("/api/leaderboard")
def api_leaderboard():
    return jsonify({"board": db.get_leaderboard(15), "live": True})


@app.route("/api/dev/stats")
def dev_stats():
    if not config.DEV_SECRET or not hmac.compare_digest(request.args.get("code", ""), config.DEV_SECRET):
        return jsonify({"ok": False}), 403
    s = db.get_stats()
    return jsonify({"ok": True, **s})


@app.route("/api/razorpay/webhook", methods=["POST"])
def razorpay_webhook():
    try:
        if not config.RAZORPAY_WEBHOOK_SECRET:
            # Never process payment events without a verified signature.
            logger.error("Razorpay webhook received but RAZORPAY_WEBHOOK_SECRET is not configured — rejecting.")
            return jsonify({"ok": False, "error": "webhook not configured"}), 503
        body = request.get_data()
        received_sig = request.headers.get("X-Razorpay-Signature", "")
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
        logger.exception("WA: %s", e)
        return jsonify({"ok": False}), 500


@app.route("/api/webhook", methods=["POST"])
def telegram_webhook():
    if config.WEBHOOK_SECRET and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != config.WEBHOOK_SECRET:
        return jsonify({"ok": False}), 401
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"ok": False}), 400
        uid = str(data.get("message", {}).get("from", {}).get("id") or
                  data.get("callback_query", {}).get("from", {}).get("id") or "tg")
        if is_rate_limited(f"tg:{uid}", max_calls=12, window_sec=60):
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
        logger.exception("TG webhook: %s", e)
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
        return jsonify({"ok": r.json().get("ok"), "telegram_webhook": webhook_url, "response": r.json()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/dev/activate-pro", methods=["POST"])
def dev_activate_pro():
    if not config.DEV_SECRET:
        return jsonify({"ok": False, "error": "dev mode disabled"}), 403
    data = request.get_json(silent=True) or {}
    if not hmac.compare_digest((data.get("code") or ""), config.DEV_SECRET):
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    uid = (data.get("uid") or "").strip()
    if not uid:
        return jsonify({"ok": False, "error": "uid required"}), 400
    db.ensure_user(uid, full_name="Pro Tester", platform="web")
    ok = db.activate_pro(uid, days=30)
    return jsonify({"ok": bool(ok), "uid": uid, "plan": "pro", "days": 30})


if __name__ == "__main__":
    # threaded=True lets Flask's dev server handle multiple concurrent
    # requests (AI calls already run off-thread via the pool, so the web
    # worker itself must not block on them). For real production traffic,
    # run behind gunicorn with multiple workers instead of this dev server:
    #   gunicorn -w 4 -k gthread --threads 8 -b 0.0.0.0:$PORT studygenie_bot:app
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), threaded=True)
