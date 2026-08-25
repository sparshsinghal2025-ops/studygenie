# ===================================================================
# STUDYGENIE - SECURITY-HARDENED VERSION
# Original by Sparsh Singhal. Patched for auth, quota-bypass, and
# data-persistence bugs found during review. See CHANGES.md.
# ===================================================================

import os
import re
import time
import json
import logging
import hmac
import hashlib
import secrets
from datetime import datetime
from collections import defaultdict
from functools import wraps

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger("studygenie")

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

try:
    import redis
    REDIS_AVAILABLE = True
except Exception:
    REDIS_AVAILABLE = False
    redis = None
    log.warning("Redis not available - using memory storage")

try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except Exception:
    GENAI_AVAILABLE = False
    genai = None
    log.warning("Gemini not available - will use fallback")

try:
    import razorpay
    RAZORPAY_AVAILABLE = True
except Exception:
    RAZORPAY_AVAILABLE = False
    razorpay = None
    log.warning("Razorpay not available - payment disabled")

# ===================================================================
# Configuration
# ===================================================================
_SECRET_KEY_ENV = os.environ.get("SECRET_KEY")
_ADMIN_TOKEN_ENV = os.environ.get("ADMIN_TOKEN")

if not _SECRET_KEY_ENV:
    log.warning(
        "SECRET_KEY not set in environment - using a random value generated at "
        "process start. On serverless platforms every cold start / instance will "
        "get a DIFFERENT secret, which breaks dev-token verification across "
        "instances. Set SECRET_KEY explicitly in production."
    )
if not _ADMIN_TOKEN_ENV:
    log.warning(
        "ADMIN_TOKEN not set in environment - using a random value generated at "
        "process start. Set ADMIN_TOKEN explicitly or you may lock yourself out "
        "of /admin/* routes, or the token may differ per instance."
    )

SECRET_KEY = _SECRET_KEY_ENV or secrets.token_urlsafe(32)
ADMIN_TOKEN = _ADMIN_TOKEN_ENV or secrets.token_urlsafe(32)
REDIS_URL = os.environ.get("REDIS_URL") or os.environ.get("UPSTASH_REDIS_URL") or os.environ.get("KV_URL")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_KEY") or ""
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
FREE_ASK_LIMIT = int(os.environ.get("FREE_ASK_LIMIT", "10"))
PRO_AMOUNT = int(os.environ.get("PRO_AMOUNT", "4900"))
DEV_PASSWORD = os.environ.get("DEV_PASSWORD", "sparsh123")

if not RAZORPAY_WEBHOOK_SECRET:
    log.warning(
        "RAZORPAY_WEBHOOK_SECRET not set - incoming payment webhooks will be "
        "REJECTED (verify_webhook always returns False without it), meaning "
        "real payments will never upgrade a user to pro. Set this in production."
    )

DEV_TOKEN = hmac.new(SECRET_KEY.encode(), b"studygenie_dev_access_v1", hashlib.sha256).hexdigest()

# ===================================================================
# Redis Client
# ===================================================================
class RedisClient:
    def __init__(self):
        self.client = None
        self.connected = False
        if REDIS_AVAILABLE and REDIS_URL:
            try:
                self.client = redis.from_url(
                    REDIS_URL,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True
                )
                self.client.ping()
                self.connected = True
                log.info("Redis connected")
            except Exception as e:
                log.warning(f"Redis connection failed: {e}")
                self.connected = False

    def get(self):
        return self.client if self.connected else None

    def is_available(self):
        return self.connected

redis_client = RedisClient()

# ===================================================================
# Auth helpers
#
# A lightweight bearer-token scheme replaces the old "just tell me your
# phone number" identity model. Registration returns a random token once;
# the client must present it (header X-Auth-Token or body "token") for any
# request that reads/writes data tied to that phone number. This is not a
# substitute for real SMS/OTP verification, but it closes the previous
# account-takeover hole where knowing a 10-digit phone number was enough
# to fully impersonate another user.
# ===================================================================
def hash_token(token):
    return hashlib.sha256((token or "").encode()).hexdigest()

def get_request_token(data):
    return request.headers.get("X-Auth-Token") or (data.get("token") if data else None) or ""

def is_dev_request(data):
    """Server-side dev-mode check. The client must present a dev_token that
    was only ever issued by /dev/verify after a correct password check -
    a plain boolean flag from the client is never trusted."""
    supplied = (data.get("dev_token") if data else None) or request.headers.get("X-Dev-Token") or ""
    return bool(supplied) and hmac.compare_digest(supplied, DEV_TOKEN)

# ===================================================================
# Storage Layer
# ===================================================================
class Storage:
    def __init__(self):
        self.users = {}                 # phone -> user dict (memory fallback)
        self.leaderboard = {}           # uid -> entry (memory fallback)
        self.ask_counts = defaultdict(int)
        self.total_asks = 0
        self.cache_ts = 0
        self.cache_data = []
        self._answer_cache = {}         # question-hash -> answer (memory fallback)
        self._users_seen = set()        # memory fallback for total_users

        try:
            import threading
            self._lock = threading.RLock()
        except Exception:
            self._lock = None

    def _get_redis(self):
        return redis_client.get()

    # ---- users -----------------------------------------------------
    def get_user(self, phone):
        if not phone:
            return None
        r = self._get_redis()
        if r:
            try:
                data = r.hgetall(f"user:{phone}")
                if data:
                    return data
            except Exception:
                pass
        return self.users.get(phone)

    def save_user(self, data):
        try:
            phone = data.get("phone")
            if not phone:
                return False

            r = self._get_redis()
            if r:
                try:
                    r.hset(f"user:{phone}", mapping=data)
                    # NOTE: previously this set a 24h TTL, which meant a
                    # paying user's "pro" status silently reverted to free
                    # after one day of inactivity. User records now persist
                    # indefinitely, consistent with the leaderboard data.
                    r.set(f"uid_to_phone:{data.get('uid')}", phone)
                    r.sadd("users", phone)
                except Exception:
                    pass

            with self._guard():
                self.users[phone] = data
                self._users_seen.add(phone)
            return True
        except Exception:
            return False

    def _guard(self):
        class _Ctx:
            def __enter__(_self):
                if self._lock:
                    self._lock.acquire()
            def __exit__(_self, *a):
                if self._lock:
                    self._lock.release()
        return _Ctx()

    def get_plan(self, phone):
        user = self.get_user(phone)
        return user.get("plan", "free") if user else "free"

    def update_plan(self, phone, plan):
        user = self.get_user(phone)
        if not user:
            user = {
                "phone": phone,
                "uid": secrets.token_urlsafe(16),
                "name": "Warrior",
                "plan": "free",
                "xp": 0,
                "level": 1,
                "token_hash": ""
            }
        user["plan"] = plan
        user["updated_at"] = datetime.utcnow().isoformat()
        return self.save_user(user)

    # ---- leaderboard -------------------------------------------------
    def get_leaderboard(self, limit=10):
        now = time.time()
        if now - self.cache_ts < 5 and self.cache_data:
            return self.cache_data

        r = self._get_redis()
        entries = []
        if r:
            try:
                items = r.zrevrange("leaderboard", 0, limit - 1, withscores=True)
                for idx, (uid, score) in enumerate(items):
                    name = r.hget(f"lb_user:{uid}", "name") or "Warrior"
                    level = int(r.hget(f"lb_user:{uid}", "level") or 1)
                    entries.append({"id": uid, "name": name, "xp": int(score), "level": level, "rank": idx + 1})
            except Exception:
                pass

        if not entries:
            sorted_users = sorted(self.leaderboard.values(), key=lambda x: x.get("xp", 0), reverse=True)[:limit]
            entries = [
                {"id": u.get("id"), "name": u.get("name", "Warrior"), "xp": u.get("xp", 0),
                 "level": u.get("level", 1), "rank": i + 1}
                for i, u in enumerate(sorted_users)
            ]

        self.cache_data = entries
        self.cache_ts = now
        return entries

    def update_leaderboard(self, uid, name, xp, phone=None, level=1):
        r = self._get_redis()
        if r:
            try:
                r.zadd("leaderboard", {uid: xp})
                # Kept in a distinct "lb_user:" namespace (separate from the
                # phone-keyed "user:" hash) purely for leaderboard display -
                # it is never used for auth or plan lookups.
                r.hset(f"lb_user:{uid}", mapping={"uid": uid, "name": name, "xp": xp, "level": level})
            except Exception:
                pass
        self.leaderboard[uid] = {"id": uid, "name": name, "xp": xp, "level": level}
        self.cache_ts = 0

    # ---- ask quota -----------------------------------------------------
    def increment_ask(self, uid):
        r = self._get_redis()
        if r:
            try:
                new_count = r.hincrby("ask_counts", uid, 1)
                r.incr("total_asks")
                today = datetime.utcnow().strftime("%Y-%m-%d")
                r.sadd(f"daily_active:{today}", uid)
                return int(new_count)
            except Exception:
                pass
        self.ask_counts[uid] = self.ask_counts.get(uid, 0) + 1
        self.total_asks += 1
        return self.ask_counts[uid]

    def get_ask_count(self, uid):
        r = self._get_redis()
        if r:
            try:
                count = r.hget("ask_counts", uid)
                if count is not None:
                    return int(count)
            except Exception:
                pass
        return self.ask_counts.get(uid, 0)

    # ---- answer cache (fast repeat answers) -----------------------------
    @staticmethod
    def _qkey(question):
        norm = re.sub(r"\s+", " ", question.strip().lower())
        return "qcache:" + hashlib.sha256(norm.encode()).hexdigest()

    def get_cached_answer(self, question):
        key = self._qkey(question)
        r = self._get_redis()
        if r:
            try:
                v = r.get(key)
                if v:
                    return v
            except Exception:
                pass
        return self._answer_cache.get(key)

    def set_cached_answer(self, question, answer):
        key = self._qkey(question)
        r = self._get_redis()
        if r:
            try:
                r.set(key, answer, ex=7 * 86400)
            except Exception:
                pass
        self._answer_cache[key] = answer

    # ---- stats -----------------------------------------------------------
    def get_stats(self):
        r = self._get_redis()
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if r:
            try:
                return {
                    "total_users": int(r.scard("users") or 0),
                    "total_asks": int(r.get("total_asks") or 0),
                    "daily_active": int(r.scard(f"daily_active:{today}") or 0),
                    "date": today,
                    "redis": True
                }
            except Exception:
                pass
        return {
            "total_users": len(self._users_seen) or len(self.users),
            "total_asks": self.total_asks,
            "daily_active": 0,
            "date": today,
            "redis": False
        }

    def list_users(self, limit=100):
        r = self._get_redis()
        if r:
            try:
                phones = list(r.smembers("users"))[:limit]
                out = []
                for p in phones:
                    u = r.hgetall(f"user:{p}")
                    if u:
                        u = dict(u)
                        u.pop("token_hash", None)
                        out.append(u)
                return out
            except Exception:
                pass
        out = list(self.users.values())[:limit]
        return [{k: v for k, v in u.items() if k != "token_hash"} for u in out]

storage = Storage()

# ===================================================================
# AI SERVICE
#
# Changes from the original:
# - No more "test call" per candidate model at startup (that was making
#   1-5 live Gemini calls just to boot, before the user's real question
#   was even sent - slow and wasteful, especially on serverless cold
#   starts). The first candidate model is picked optimistically and
#   verified lazily on the first real request; if it fails we fall
#   through to the next model in the same request instead of a
#   separate round-trip.
# - GenerativeModel clients are cached per model name instead of
#   recreated on every call.
# - Lower temperature + explicit "don't guess" instruction for better
#   factual/numerical accuracy.
# - generate() now returns (text, was_ai_generated) so the caller can
#   decide whether the answer is safe to cache.
# ===================================================================
PREFERRED_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-pro", "gemini-1.0-pro"]

class AIService:
    def __init__(self):
        self.is_working = bool(GENAI_AVAILABLE and GOOGLE_API_KEY)
        self.current_model = PREFERRED_MODELS[0] if self.is_working else None
        self._clients = {}
        self.last_error = None          # human-readable reason the last call failed, if any
        self.last_success_at = None     # timestamp of last confirmed real AI answer
        self.config_error = None        # why is_working is False, if it is

        if not GENAI_AVAILABLE:
            self.config_error = "google-generativeai package not installed"
        elif not GOOGLE_API_KEY:
            self.config_error = "GOOGLE_API_KEY / GEMINI_KEY environment variable is not set"

        if self.is_working:
            try:
                genai.configure(api_key=GOOGLE_API_KEY)
                log.info(f"AI configured - will try '{self.current_model}' first, lazily, on first request")
            except Exception as e:
                log.error(f"AI configure failed: {e}")
                self.is_working = False
                self.config_error = f"genai.configure() failed: {e}"

    def _client_for(self, model_name):
        client = self._clients.get(model_name)
        if client is None:
            client = genai.GenerativeModel(model_name)
            self._clients[model_name] = client
        return client

    def generate(self, question, name="Warrior", is_dev=False):
        """Returns (answer_text, was_ai_generated)."""
        if not self.is_working:
            return self._get_smart_fallback(question, name), False
        return self._generate_response(question, name)

    def _build_prompt(self, question, name):
        return f"""You are StudyGenie, an AI tutor created by Sparsh Singhal.
User: {name}
Question: {question}

Answer accurately and concisely:
- For numerical/math problems: show the key steps and the final answer clearly, and double-check the arithmetic before answering.
- For conceptual questions: give a clear, correct explanation.
- If you are not confident in an answer, say so rather than guessing.
- Use simple language with a light Hinglish mix.
- Be encouraging, but keep the answer focused - no filler.

RESPONSE:"""

    def _generate_response(self, question, name):
        prompt = self._build_prompt(question, name)
        # Try the model that worked last time first, then the rest of the
        # preferred list, all within this one request/response cycle.
        ordered = [self.current_model] + [m for m in PREFERRED_MODELS if m != self.current_model]

        last_err = None
        for model_name in ordered:
            try:
                client = self._client_for(model_name)
                response = client.generate_content(
                    prompt,
                    generation_config={
                        "max_output_tokens": 700,
                        "temperature": 0.4,   # lower than the original 0.7 - favors correctness over flair
                    },
                    request_options={"timeout": 8},  # keep well under typical platform request timeouts
                )
                if response and response.text:
                    self.current_model = model_name
                    self.last_error = None
                    self.last_success_at = datetime.utcnow().isoformat()
                    return response.text.strip(), True
            except Exception as e:
                last_err = e
                log.warning(f"Model {model_name} failed: {e}")
                continue

        self.last_error = str(last_err) if last_err else "unknown error"
        log.error(f"All models failed, last error: {last_err}")
        return self._get_smart_fallback(question, name), False

    def _get_smart_fallback(self, question, name):
        if re.search(r'[\d\+\-\*\/\(\)]', question):
            return f"""Oye {name}! Sparsh Singhal ka Genie bol raha hai!

Main yeh math problem solve kar sakta hoon, but thoda technical glitch ho gaya!

Try karo:
- Direct calculation: "2+3"
- Ya question clear karo

AI is reloading! - BY SPARSH SINGHAL"""
        if '?' in question:
            return f"""Great question, {name}!

Sparsh Singhal ka StudyGenie is thinking!

Could you please rephrase your question or try again?
Sometimes technical glitches happen, but I'm here to help!

- BY SPARSH SINGHAL"""
        return f"""Oye {name}! Sparsh Singhal ka StudyGenie ready hai!

Kuch technical glitch ho gaya, but main hoon na!

Try karo:
- Question ko simple words mein poocho
- Direct number daalo for math problems
- Koi specific topic mention karo

I'll answer everything! - BY SPARSH SINGHAL"""

ai_service = AIService()

# ===================================================================
# Payment Service
# ===================================================================
class PaymentService:
    def __init__(self):
        self.client = None
        self.is_working = False
        if RAZORPAY_AVAILABLE and RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
            try:
                self.client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
                self.is_working = True
                log.info("Razorpay initialized")
            except Exception as e:
                log.error(f"Razorpay init failed: {e}")

    def create_order(self, uid, phone, name):
        if not self.is_working or not self.client:
            return False, None, "Payment not configured"
        try:
            order = self.client.order.create({
                "amount": PRO_AMOUNT,
                "currency": "INR",
                "receipt": f"sg_{uid}_{int(time.time())}",
                "notes": {"uid": uid, "name": name, "phone": phone}
            })
            return True, {
                "order_id": order["id"],
                "amount": order["amount"],
                "currency": order["currency"],
                "key_id": RAZORPAY_KEY_ID
            }, ""
        except Exception as e:
            log.error(f"Order error: {e}")
            return False, None, str(e)

    def verify_webhook(self, payload, signature):
        if not RAZORPAY_WEBHOOK_SECRET:
            log.error("Webhook received but RAZORPAY_WEBHOOK_SECRET is not configured - rejecting. "
                       "Set this env var or payments will never upgrade anyone.")
            return False
        expected = hmac.new(RAZORPAY_WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def process_payment(self, data):
        try:
            notes = data.get("notes", {})
            phone = notes.get("phone", "")
            uid = notes.get("uid", "")
            name = notes.get("name", "Warrior")
            if not phone or not uid:
                return False
            storage.update_plan(phone, "pro")
            user = storage.get_user(phone)
            if user:
                storage.update_leaderboard(uid, user.get("name", name), user.get("xp", 0), phone, user.get("level", 1))
            log.info(f"PRO unlocked: {phone}")
            return True
        except Exception as e:
            log.error(f"Payment process error: {e}")
            return False

payment_service = PaymentService()

# ===================================================================
# Helpers
# ===================================================================
def clean_phone(phone):
    if not phone:
        return ""
    phone = re.sub(r'[^0-9]', '', str(phone))[:10]
    return phone if re.match(r"^\d{10}$", phone) else ""

def clean_name(name):
    if not name:
        return "Warrior"
    return re.sub(r'[<>"\'\\]', '', str(name))[:50]

def generate_uid():
    return secrets.token_urlsafe(16)

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not ADMIN_TOKEN:
            return jsonify({"error": "Admin not configured"}), 500
        supplied = request.headers.get("X-Admin-Token") or request.args.get("token")
        if not supplied or not hmac.compare_digest(supplied, ADMIN_TOKEN):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

def require_phone_auth(phone, data):
    """Returns (ok, error_response_or_None). Verifies the caller actually
    owns `phone` by checking the bearer token issued at registration
    against the stored hash. Call this before trusting a phone number for
    anything identity- or plan-related."""
    user = storage.get_user(phone)
    if not user:
        return False, (jsonify({"error": "Unknown phone - register first"}), 404)
    token = get_request_token(data)
    stored_hash = user.get("token_hash", "")
    if not token or not stored_hash or not hmac.compare_digest(hash_token(token), stored_hash):
        return False, (jsonify({"error": "Invalid or missing auth token for this phone number"}), 403)
    return True, None

# ===================================================================
# Flask App
# ===================================================================
app = Flask(__name__)
app.secret_key = SECRET_KEY
CORS(app, resources={r"/*": {"origins": "*"}})

# ===================================================================
# Routes
# ===================================================================
@app.route("/")
def home():
    return HTML_PAGE

@app.route("/sparsh.jpg")
def photo():
    try:
        return send_from_directory(".", "sparsh.jpg")
    except Exception:
        return "", 204

@app.route("/register_user", methods=["POST"])
def register_user():
    try:
        data = request.get_json(silent=True) or {}
        phone = clean_phone(data.get("phone"))
        name = clean_name(data.get("name", "Warrior"))

        if not phone:
            return jsonify({"error": "Valid 10-digit phone required"}), 400

        existing = storage.get_user(phone)
        if existing:
            # SECURITY: previously this returned the existing user's uid to
            # ANYONE who supplied their phone number, with no proof of
            # ownership - a full account-takeover primitive. Now it requires
            # the token that was handed out at original registration.
            ok, err = require_phone_auth(phone, data)
            if not ok:
                return err
            return jsonify({
                "ok": True,
                "uid": existing.get("uid"),
                "name": existing.get("name"),
                "phone": existing.get("phone"),
                "plan": existing.get("plan", "free"),
                "token": get_request_token(data),
            })

        uid = generate_uid()
        raw_token = secrets.token_urlsafe(24)
        user_data = {
            "phone": phone,
            "uid": uid,
            "name": name,
            "plan": "free",
            "xp": 0,
            "level": 1,
            "token_hash": hash_token(raw_token),
            "created_at": datetime.utcnow().isoformat()
        }

        if storage.save_user(user_data):
            storage.update_leaderboard(uid, name, 0, phone, 1)
            log.info(f"User registered: {phone}")
            return jsonify({
                "ok": True,
                "uid": uid,
                "name": name,
                "phone": phone,
                "plan": "free",
                "token": raw_token,   # returned ONCE - client must store it
            })

        return jsonify({"error": "Failed to save user"}), 500

    except Exception as e:
        log.error(f"Register error: {e}")
        return jsonify({"error": "Registration failed"}), 500

@app.route("/leaderboard")
def get_leaderboard():
    try:
        limit = min(int(request.args.get("limit", 10)), 100)
        return jsonify(storage.get_leaderboard(limit))
    except Exception:
        return jsonify([]), 200

@app.route("/ask", methods=["POST"])
def ask():
    try:
        start_time = time.time()
        data = request.get_json(silent=True) or {}
        question = (data.get("q") or "").strip()
        name = clean_name(data.get("name", "Warrior"))
        uid = str(data.get("uid", "anon"))[:64]
        phone_claim = clean_phone(data.get("phone"))

        if len(question) > 2000:
            question = question[:2000]
        if not question:
            return jsonify({"error": "Empty question"}), 400

        # SECURITY: dev mode is decided ENTIRELY server-side now. A client
        # can no longer just send {"dev": true} to bypass quota - it must
        # present a dev_token obtained from /dev/verify with the real
        # password. See is_dev_request().
        is_dev = is_dev_request(data)

        # SECURITY: a phone number only counts for plan/XP purposes if the
        # caller can prove ownership of it. Otherwise we silently treat the
        # request as an anonymous free-tier ask rather than granting
        # someone else's plan/XP to a spoofed phone number.
        phone = ""
        if phone_claim:
            ok, _err = require_phone_auth(phone_claim, data)
            if ok:
                phone = phone_claim
            elif not is_dev:
                return jsonify({"error": "Invalid or missing auth token for this phone number"}), 403

        plan = storage.get_plan(phone) if phone else "free"
        used = storage.get_ask_count(uid)

        if not is_dev and plan == "free" and used >= FREE_ASK_LIMIT:
            return jsonify({
                "limit_reached": True,
                "ans": f"""AMMO KHATAM!

Oye {name}! Your free ammo is over!

RELOAD NOW - Rs.49 Only!
Click "RELOAD" button below!

- BY SPARSH SINGHAL"""
            }), 402

        # Fast path: serve a cached answer for a question we've already
        # answered correctly before, instead of round-tripping to the model.
        cached = storage.get_cached_answer(question)
        if cached:
            response_text = cached
        else:
            response_text, was_ai = ai_service.generate(question, name, is_dev)
            if was_ai:
                storage.set_cached_answer(question, response_text)

        if not is_dev:
            storage.increment_ask(uid)

        user = storage.get_user(phone) if phone else None
        xp_gained = 0
        level_up = False

        if user and not is_dev:
            xp_gained = 25 if plan == "pro" else 10
            user["xp"] = user.get("xp", 0) + xp_gained
            if user["xp"] >= user.get("level", 1) * 100:
                user["level"] = user.get("level", 1) + 1
                level_up = True
            storage.save_user(user)
            storage.update_leaderboard(uid, user.get("name", name), user.get("xp", 0), phone, user.get("level", 1))

        elapsed = time.time() - start_time
        log.info(f"Ask completed in {elapsed:.2f}s (cached={bool(cached)})")

        return jsonify({
            "ans": response_text,
            "xp_gained": xp_gained if not is_dev else 0,
            "level_up": level_up if not is_dev else False,
            "level": user.get("level", 1) if user else 1,
            "dev_mode": is_dev,
            "cached": bool(cached),
        })

    except Exception as e:
        log.error(f"Ask error: {e}")
        return jsonify({"ans": "Try again! - BY SPARSH SINGHAL"}), 500

@app.route("/dev/verify", methods=["POST"])
def dev_verify():
    """Server-side password check. Returns a dev_token only on success;
    that token (not a boolean) is what /ask actually trusts."""
    data = request.get_json(silent=True) or {}
    password = data.get("password", "")
    if not password or not hmac.compare_digest(password, DEV_PASSWORD):
        time.sleep(0.3)  # slow down brute force a little
        return jsonify({"error": "Invalid password"}), 401
    return jsonify({"ok": True, "dev_token": DEV_TOKEN})

@app.route("/create_order", methods=["POST"])
def create_order():
    try:
        data = request.get_json(silent=True) or {}
        phone = clean_phone(data.get("phone"))
        name = clean_name(data.get("name", "Warrior"))
        uid = str(data.get("uid", ""))[:64]

        if not phone:
            return jsonify({"error": "Phone required"}), 400
        if not uid:
            return jsonify({"error": "UID required"}), 400

        ok, err = require_phone_auth(phone, data)
        if not ok:
            return err

        success, result, error = payment_service.create_order(uid, phone, name)
        if success:
            return jsonify(result)
        return jsonify({"error": error}), 500

    except Exception as e:
        log.error(f"Create order error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/razorpay/webhook", methods=["POST"])
def webhook():
    try:
        payload = request.get_data()
        signature = request.headers.get("X-Razorpay-Signature", "")
        if not payment_service.verify_webhook(payload, signature):
            log.warning("Invalid or unverifiable webhook signature")
            return jsonify({"error": "Invalid signature"}), 400

        event = request.get_json(silent=True) or {}
        if event.get("event") == "payment.captured":
            payment = event.get("payload", {}).get("payment", {}).get("entity", {})
            if payment:
                payment_service.process_payment(payment)
        return jsonify({"status": "ok"})

    except Exception as e:
        log.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/check_plan", methods=["POST"])
def check_plan():
    try:
        data = request.get_json(silent=True) or {}
        phone = clean_phone(data.get("phone"))
        if not phone:
            return jsonify({"plan": "free"}), 200
        ok, err = require_phone_auth(phone, data)
        if not ok:
            return err
        return jsonify({"plan": storage.get_plan(phone)})
    except Exception:
        return jsonify({"plan": "free"}), 200

@app.route("/admin/ai_status")
@admin_required
def admin_ai_status():
    """Quick diagnostic: is the real AI configured and working, or are
    users silently getting the pre-defined fallback message? Check this
    first whenever answers look canned/repetitive."""
    return jsonify({
        "genai_package_installed": GENAI_AVAILABLE,
        "google_api_key_set": bool(GOOGLE_API_KEY),
        "is_working": ai_service.is_working,
        "config_error": ai_service.config_error,
        "current_model": ai_service.current_model,
        "last_generation_error": ai_service.last_error,
        "last_successful_answer_at": ai_service.last_success_at,
    })

@app.route("/admin/stats")
@admin_required
def admin_stats():
    try:
        return jsonify(storage.get_stats())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/admin/users")
@admin_required
def admin_users():
    try:
        users = storage.list_users(100)
        return jsonify({"users": users, "total": len(users)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/admin/force_pro", methods=["POST"])
@admin_required
def admin_force_pro():
    try:
        data = request.get_json(silent=True) or {}
        phone = clean_phone(data.get("phone"))
        if not phone:
            return jsonify({"error": "Phone required"}), 400
        if storage.update_plan(phone, "pro"):
            return jsonify({"ok": True, "phone": phone, "plan": "pro"})
        return jsonify({"error": "Failed"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# NOTE: the old public /update_xp endpoint has been removed. It let anyone
# set arbitrary XP/level for any uid with no auth at all (verified: a
# stranger could set uid "victim" to level 1000). XP is now derived only
# from real, server-tracked /ask activity - there is no client-writable
# XP endpoint. If you need an admin XP override, add it under
# @admin_required rather than as a public route.

# ===================================================================
# HTML
# ===================================================================
HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>StudyGenie</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: #050507; color: #fff; font-family: system-ui, sans-serif; min-height: 100vh; background-image: radial-gradient(circle at 50% 0%, #1a1208 0%, #050507 60%); }
.hud { background: rgba(17,17,19,0.95); border: 1px solid #232326; border-radius: 16px; padding: 20px; backdrop-filter: blur(10px); }
.btn-fire { background: linear-gradient(90deg, #ff4d00, #ff8a00); border: none; padding: 12px 28px; border-radius: 12px; font-weight: 900; cursor: pointer; color: #fff; font-size: 16px; transition: all 0.3s; }
.btn-fire:hover { transform: scale(1.05); box-shadow: 0 0 30px rgba(255,77,0,0.4); }
.btn-fire:active { transform: scale(0.95); }
.bubble-ai { background: #17171a; border-left: 4px solid #ff4d00; border-radius: 4px 16px 16px 16px; padding: 14px 18px; white-space: pre-wrap; line-height: 1.8; }
.bubble-user { background: #fff; color: #000; border-radius: 14px 14px 2px 14px; padding: 12px 18px; font-weight: 900; display: inline-block; }
.progress { height: 14px; background: #0f0f11; border: 1px solid #2a2a2e; border-radius: 4px; overflow: hidden; }
.progress > div { height: 100%; background: linear-gradient(90deg, #ff4d00, #ff8a00); transition: width 0.5s; }
.ammo { width: 42px; height: 52px; background: #121216; border: 2px solid #2e2e33; border-radius: 8px; display: inline-flex; align-items: center; justify-content: center; margin: 2px; font-size: 20px; transition: all 0.3s; }
.ammo.used { opacity: 0.15; transform: scale(0.85); }
#chat { max-height: 55vh; overflow-y: auto; scroll-behavior: smooth; }
#chat::-webkit-scrollbar { width: 4px; }
#chat::-webkit-scrollbar-track { background: #0f0f11; }
#chat::-webkit-scrollbar-thumb { background: #ff4d00; border-radius: 4px; }
.input-glow:focus { border-color: #ff4d00 !important; box-shadow: 0 0 20px rgba(255,77,0,0.2); }
@keyframes slideIn { from { opacity: 0; transform: translateX(-20px); } to { opacity: 1; transform: translateX(0); } }
.bubble-ai { animation: slideIn 0.3s ease-out; }
.dev-badge { background: #ff4d00; color: #fff; font-size: 10px; padding: 2px 8px; border-radius: 10px; display: none; font-weight: 900; }
</style>
</head>
<body>

<div id="onboard" style="position:fixed;inset:0;background:rgba(0,0,0,0.97);display:flex;align-items:center;justify-content:center;z-index:999;backdrop-filter:blur(10px)">
  <div class="hud max-w-[420px] w-full">
    <div class="flex items-center gap-4">
      <img src="/sparsh.jpg" class="w-16 h-16 rounded-xl border-2 border-[#ff4d00] object-cover">
      <div>
        <h2 class="text-2xl font-black">REGISTER</h2>
        <p class="text-[#ff8a00] text-sm font-bold">BY SPARSH SINGHAL</p>
      </div>
    </div>
    <p class="text-sm text-zinc-400 mt-3">Enter the battlefield, warrior!</p>
    <div class="mt-4 space-y-3">
      <input id="inpName" class="w-full bg-black border-2 border-zinc-800 rounded-xl px-4 py-3 text-white outline-none input-glow" placeholder="Your Name" maxlength="20">
      <input id="inpPhone" class="w-full bg-black border-2 border-zinc-800 rounded-xl px-4 py-3 text-white outline-none input-glow" placeholder="10 digit phone" maxlength="10" type="tel">
    </div>
    <button onclick="registerUser()" class="btn-fire w-full mt-4" id="registerBtn">ENTER BATTLEFIELD</button>
    <p id="registerStatus" class="text-xs text-zinc-500 mt-2 text-center"></p>
  </div>
</div>

<div id="app" style="display:none;max-width:1500px;margin:0 auto;padding:16px">
  <div class="hud flex justify-between items-center sticky top-2 z-30">
    <div class="flex items-center gap-6">
      <img id="logo" src="/sparsh.jpg" class="w-24 h-24 rounded-[16px] border-4 border-[#ff4d00] object-cover cursor-pointer" onclick="handleLogoClick()">
      <div>
        <h1 class="text-2xl font-black tracking-wider">STUDYGENIE</h1>
        <p class="text-[#ff8a00] text-sm font-bold">BY SPARSH SINGHAL</p>
        <div class="flex items-center gap-3 mt-2">
          <span class="text-xs text-zinc-400">XP</span>
          <div class="progress w-40"><div id="xpBar" style="width:0%"></div></div>
          <span id="xpText" class="text-xs font-bold">0/100</span>
        </div>
        <p class="text-xs text-zinc-600">LVL <span id="lvl">1</span> | <span id="userName" class="text-[#ff4d00]">WARRIOR</span></p>
      </div>
    </div>
    <div class="flex items-center gap-4">
      <div id="devBadge" class="dev-badge">DEV</div>
      <div class="text-right">
        <div class="text-xs text-zinc-500 tracking-widest">AMMO</div>
        <div class="text-3xl font-black"><span id="ammoLeft">10</span>/10</div>
      </div>
      <div class="w-px h-12 bg-zinc-800"></div>
      <div class="text-right">
        <div class="text-xs text-zinc-500 tracking-widest">PLAN</div>
        <div id="planDisplay" class="font-bold text-[#ff8a00]">FREE</div>
      </div>
    </div>
  </div>

  <div class="grid grid-cols-12 gap-4 mt-4">
    <div class="col-span-12 lg:col-span-3 space-y-4">
      <div class="hud">
        <p class="text-xs text-zinc-500 tracking-widest">MISSIONS</p>
        <div class="bg-black p-3 rounded mt-2 border-l-4 border-[#ff4d00]">
          <div class="flex justify-between text-sm font-bold"><span>3 DOUBTS</span><span id="q1">0/3</span></div>
          <div class="progress mt-1"><div id="q1b" style="width:0%"></div></div>
        </div>
        <div class="bg-black p-3 rounded mt-2 border-l-4 border-[#ff8a00]">
          <div class="flex justify-between text-sm font-bold"><span>10 QUESTIONS</span><span id="q2">0/10</span></div>
          <div class="progress mt-1"><div id="q2b" style="width:0%"></div></div>
        </div>
      </div>

      <div class="hud">
        <p class="text-xs text-zinc-500 tracking-widest">AMMO CRATE</p>
        <div id="lamps" class="mt-2"></div>
        <button onclick="openPay()" class="btn-fire w-full mt-3 text-sm">RELOAD - Rs.49</button>
      </div>

      <div class="hud">
        <p class="text-xs text-[#ff4d00] tracking-widest font-black">LEADERBOARD</p>
        <div id="board" class="mt-2 space-y-1"></div>
        <div class="mt-2 text-xs text-zinc-500 bg-black p-2 rounded border border-zinc-800">
          <span class="text-[#ff8a00]">PRIVATE</span><br>
          <span id="myId"></span><br>
          <span id="myPhone"></span>
        </div>
      </div>
    </div>

    <div class="col-span-12 lg:col-span-9">
      <div class="hud" style="min-height:500px">
        <div id="chat" class="space-y-3"></div>
        <div class="mt-4 flex gap-2">
          <span class="text-[#ff4d00] font-black text-xl">></span>
          <input id="q" class="flex-1 bg-black border-2 border-zinc-800 rounded-xl px-4 py-3 text-white outline-none input-glow" placeholder="ANY QUESTION... I'll solve it!" onkeypress="if(event.key==='Enter')ask()">
          <button onclick="ask()" class="btn-fire">ASK</button>
        </div>
        <div class="mt-2 flex justify-between text-xs text-zinc-500">
          <span>10 free questions, then Rs.49 for unlimited!</span>
          <span>By Sparsh Singhal</span>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
const STORAGE_KEY = 'studygenie_data';
let appData = {
  userId: 'user_' + Math.random().toString(36).substr(2,9),
  name: '',
  phone: '',
  token: '',       // auth token issued by /register_user - proves phone ownership
  isPro: false,
  isDev: false,
  devToken: '',    // issued by /dev/verify after a correct password check
  stats: { xp: 0, level: 1, wishes: 0, q1: 0, q2: 0, totalXp: 0 }
};

function loadData() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      const data = JSON.parse(saved);
      appData = { ...appData, ...data };
    }
  } catch(e) {}
}
function saveData() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(appData)); } catch(e) {}
}
loadData();

let audioCtx = null;
function playSound(type) {
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.connect(gain); gain.connect(audioCtx.destination);
    gain.gain.setValueAtTime(0.2, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.15);
    osc.start(); osc.stop(audioCtx.currentTime + 0.15);
  } catch(e) {}
}

// ---- Dev mode: password is verified SERVER-SIDE via /dev/verify now.
// The client never decides dev mode itself - it only stores whatever
// dev_token the server hands back after a correct password.
let logoClickCount = 0;
let logoClickTimer = null;
function handleLogoClick() {
  playSound('click');
  logoClickCount++;
  clearTimeout(logoClickTimer);
  logoClickTimer = setTimeout(() => { logoClickCount = 0; }, 3000);
  if (logoClickCount >= 5) {
    logoClickCount = 0;
    const password = prompt('Enter Secret Code:');
    if (password === null) return;
    fetch('/dev/verify', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ password })
    }).then(r => r.json()).then(data => {
      if (data.ok && data.dev_token) {
        appData.isDev = !appData.isDev;
        appData.devToken = appData.isDev ? data.dev_token : '';
        saveData();
        document.getElementById('devBadge').style.display = appData.isDev ? 'inline-block' : 'none';
        playSound(appData.isDev ? 'level' : 'empty');
        alert(appData.isDev ? 'DEV MODE ACTIVATED! Unlimited free questions!' : 'DEV MODE DEACTIVATED');
        render();
      } else {
        playSound('empty');
        alert('ACCESS DENIED!');
      }
    }).catch(() => { playSound('empty'); alert('Network error'); });
  }
}

function registerUser() {
  const nameInput = document.getElementById('inpName');
  const phoneInput = document.getElementById('inpPhone');
  const statusEl = document.getElementById('registerStatus');
  const btn = document.getElementById('registerBtn');

  const name = nameInput.value.trim();
  const phone = phoneInput.value.trim().replace(/[^0-9]/g, '');

  if (!name || name.length < 2) {
    statusEl.textContent = 'Please enter your name!'; statusEl.style.color = '#ff4444'; playSound('empty'); return;
  }
  if (!phone || phone.length !== 10) {
    statusEl.textContent = 'Please enter a valid 10-digit phone number!'; statusEl.style.color = '#ff4444'; playSound('empty'); return;
  }

  statusEl.textContent = 'Registering...'; statusEl.style.color = '#ff8a00';
  btn.disabled = true; btn.textContent = 'WAIT...';

  // If we already have a saved token for this phone (same device,
  // returning user), send it along so the server recognizes us.
  const body = { uid: appData.userId, name: name, phone: phone };
  if (appData.phone === phone && appData.token) body.token = appData.token;

  fetch('/register_user', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
  })
  .then(res => res.json().then(data => ({ status: res.status, data })))
  .then(({status, data}) => {
    if (data.ok) {
      appData.name = name; appData.phone = phone; appData.token = data.token || appData.token;
      saveData();
      statusEl.textContent = 'Welcome ' + name + '!'; statusEl.style.color = '#44ff88';
      playSound('level');
      setTimeout(() => {
        document.getElementById('onboard').style.display = 'none';
        document.getElementById('app').style.display = 'block';
        initApp();
      }, 500);
    } else if (status === 403) {
      statusEl.textContent = 'This phone is already registered on another device. Use the same device/browser you first signed up with.';
      statusEl.style.color = '#ff4444';
      btn.disabled = false; btn.textContent = 'ENTER BATTLEFIELD';
    } else {
      statusEl.textContent = (data.error || 'Registration failed');
      statusEl.style.color = '#ff4444';
      btn.disabled = false; btn.textContent = 'ENTER BATTLEFIELD';
    }
  })
  .catch(() => {
    statusEl.textContent = 'Network error. Please try again.'; statusEl.style.color = '#ff4444';
    btn.disabled = false; btn.textContent = 'ENTER BATTLEFIELD';
  });
}

function initApp() {
  document.getElementById('userName').textContent = appData.name.toUpperCase();
  document.getElementById('myId').textContent = 'ID ' + appData.userId;
  document.getElementById('myPhone').textContent = 'PHONE ' + appData.phone.slice(0,2) + '******' + appData.phone.slice(-2);
  if (appData.isDev) document.getElementById('devBadge').style.display = 'inline-block';
  render(); loadBoard(); checkPlan();
  setInterval(loadBoard, 10000);
}

function render() {
  const s = appData.stats;
  const unlimited = appData.isPro || appData.isDev;
  document.getElementById('ammoLeft').textContent = unlimited ? String.fromCharCode(8734) : (10 - s.wishes);
  document.getElementById('lvl').textContent = s.level;
  document.getElementById('xpBar').style.width = Math.min(100, s.xp) + '%';
  document.getElementById('xpText').textContent = s.xp + '/100';
  document.getElementById('q1').textContent = s.q1 + '/3';
  document.getElementById('q1b').style.width = (s.q1/3*100) + '%';
  document.getElementById('q2').textContent = s.q2 + '/10';
  document.getElementById('q2b').style.width = (s.q2/10*100) + '%';

  let planText = 'FREE', planClass = 'font-bold text-[#ff8a00]';
  if (appData.isPro) { planText = 'PRO'; planClass = 'font-bold text-[#ff4d00]'; }
  if (appData.isDev) { planText = 'DEV'; planClass = 'font-bold text-[#00ff88]'; }
  document.getElementById('planDisplay').textContent = planText;
  document.getElementById('planDisplay').className = planClass;

  let html = '';
  for (let i = 0; i < 10; i++) {
    let used = i < s.wishes && !appData.isPro && !appData.isDev;
    html += `<div class="ammo${used ? ' used' : ''}">${used ? 'X' : 'O'}</div>`;
  }
  document.getElementById('lamps').innerHTML = html;
}

function appendBubble(text, isUser = false) {
  const chat = document.getElementById('chat');
  const div = document.createElement('div');
  div.className = isUser ? 'text-right mb-3' : 'mb-3';
  const bubble = document.createElement('div');
  bubble.className = isUser ? 'bubble-user' : 'bubble-ai';
  bubble.textContent = text;
  if (!isUser) {
    const wrapper = document.createElement('div');
    wrapper.className = 'flex gap-3';
    const img = document.createElement('img');
    img.src = '/sparsh.jpg';
    img.className = 'w-10 h-10 rounded-xl border-2 border-[#ff4d00] object-cover';
    wrapper.appendChild(img); wrapper.appendChild(bubble);
    div.appendChild(wrapper);
  } else {
    div.appendChild(bubble);
  }
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

async function ask() {
  if (!appData.name || !appData.phone) {
    document.getElementById('onboard').style.display = 'flex'; return;
  }
  const input = document.getElementById('q');
  const q = input.value.trim();
  if (!q) { playSound('empty'); return; }

  playSound('fire');
  appendBubble(q, true);
  input.value = '';

  const typingDiv = document.createElement('div');
  typingDiv.className = 'mb-3';
  typingDiv.innerHTML = '<div class="bubble-ai text-zinc-400">Thinking...</div>';
  document.getElementById('chat').appendChild(typingDiv);

  try {
    const body = { q, name: appData.name, phone: appData.phone, uid: appData.userId, token: appData.token };
    if (appData.isDev && appData.devToken) body.dev_token = appData.devToken;

    const res = await fetch('/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    typingDiv.remove();
    const data = await res.json();

    if (res.status === 403) {
      appendBubble('Session expired for this phone number - please re-enter the battlefield.', false);
      return;
    }
    if (res.status === 402 || data.limit_reached) {
      playSound('empty');
      appendBubble(data.ans, false);
      setTimeout(openPay, 2000);
      return;
    }

    const s = appData.stats;
    if (!appData.isDev) {
      s.wishes++;
      s.q1 = Math.min(3, s.q1 + 1);
      s.q2 = Math.min(10, s.q2 + 1);
      s.xp += data.xp_gained || 10;
      s.totalXp = (s.totalXp || 0) + (data.xp_gained || 10);
    }
    if (data.level_up && !appData.isDev) {
      s.level = data.level;
      playSound('level');
      appendBubble('LEVEL UP - LVL ' + data.level + '!', false);
    }

    saveData(); render(); playSound('hit');
    appendBubble(data.ans, false);

  } catch(e) {
    typingDiv.remove();
    appendBubble('Try again! - BY SPARSH SINGHAL', false);
  }
}

async function loadBoard() {
  try {
    const res = await fetch('/leaderboard');
    const data = await res.json();
    let html = '';
    if (data.length === 0) {
      html = '<div class="text-zinc-500 text-center py-2">No warriors yet</div>';
    } else {
      data.forEach((u, i) => {
        const isMe = u.id === appData.userId;
        const medal = i === 0 ? '1.' : i === 1 ? '2.' : i === 2 ? '3.' : `${i+1}.`;
        html += `<div class="flex justify-between items-center p-2 rounded border ${isMe ? 'bg-[#ff4d00]/20 border-[#ff4d00]/50' : 'bg-black border-zinc-800'}">
          <span class="text-sm">${medal} ${u.name} ${isMe ? '(you)' : ''}</span>
          <span class="text-[#ff4d00] font-bold">${u.xp}XP</span>
        </div>`;
      });
    }
    document.getElementById('board').innerHTML = html;
  } catch(e) {}
}

async function checkPlan() {
  if (!appData.phone || !appData.token) return;
  try {
    const res = await fetch('/check_plan', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone: appData.phone, token: appData.token })
    });
    const data = await res.json();
    if (data.plan === 'pro') { appData.isPro = true; saveData(); render(); }
  } catch(e) {}
}

async function openPay() {
  if (!appData.phone || appData.phone.length !== 10) {
    document.getElementById('onboard').style.display = 'flex'; return;
  }
  try {
    const res = await fetch('/create_order', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uid: appData.userId, name: appData.name, phone: appData.phone, token: appData.token })
    });
    const order = await res.json();
    if (order.error) { alert(order.error); return; }

    const options = {
      key: order.key_id, amount: order.amount, currency: order.currency,
      name: "StudyGenie Pro", order_id: order.order_id,
      prefill: { name: appData.name, contact: appData.phone },
      theme: { color: "#ff4d00" },
      handler: function() {
        alert('Payment received - PRO will unlock once confirmed.');
        location.reload();
      }
    };
    new Razorpay(options).open();
  } catch(e) {
    alert('Error: ' + e.message);
  }
}

function checkOnboard() {
  if (appData.name && appData.phone && appData.phone.length === 10 && appData.token) {
    document.getElementById('onboard').style.display = 'none';
    document.getElementById('app').style.display = 'block';
    initApp();
  } else {
    document.getElementById('onboard').style.display = 'flex';
    document.getElementById('app').style.display = 'none';
  }
}

document.getElementById('chat').innerHTML = `
<div class="flex gap-3">
  <img src="/sparsh.jpg" class="w-12 h-12 rounded-xl border-2 border-[#ff4d00] object-cover">
  <div class="bubble-ai">
    <b>OYE WARRIOR!</b><br><br>
    Main hoon <b>Sparsh Singhal ka StudyGenie</b><br><br>
    Physics Numericals -> Full solution<br>
    Math Problems -> Step-by-step<br>
    ANY Question -> Answered!<br><br>
    <b>Kuch bhi pucho!</b><br><br>
    <span class="text-[#ff8a00] text-xs">BY SPARSH SINGHAL | 10 FREE AMMO</span>
  </div>
</div>
`;

checkOnboard();
</script>
</body></html>
"""

# ===================================================================
# Local Development / Vercel entrypoint
#
# Vercel's Python runtime auto-detects a Flask instance named `app` at a
# supported entrypoint file (app.py, index.py, server.py, main.py, ...)
# and routes requests to it directly - no custom handler function needed.
# The previous `def handler(request, context): return app(request, context)`
# used an AWS-Lambda-style signature that doesn't match Vercel's WSGI
# convention and has been removed; just deploying this file with `app`
# exposed is sufficient.
# ===================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"StudyGenie starting on http://localhost:{port}")
    print(f"Model (lazy): {ai_service.current_model if ai_service.is_working else 'FALLBACK'}")
    print(f"Redis: {'Connected' if redis_client.is_available() else 'Memory Mode'}")
    print(f"Payments: {'Enabled' if payment_service.is_working else 'Disabled'}")
    app.run(host="0.0.0.0", port=port, debug=False)
