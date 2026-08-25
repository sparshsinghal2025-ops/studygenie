# ===================================================================
# STUDYGENIE - VERCEL FIXED VERSION
# By Sparsh Singhal
# ===================================================================

import os
import sys
import re
import time
import json
import logging
import hmac
import hashlib
import secrets
from datetime import datetime
from collections import defaultdict
from typing import Optional, Dict, Any, List, Tuple
from functools import wraps

# ===================================================================
# CRITICAL: Set up logging BEFORE anything else
# ===================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger("studygenie")

# ===================================================================
# Flask imports (minimal)
# ===================================================================
try:
    from flask import Flask, request, jsonify, send_from_directory
except ImportError as e:
    log.error(f"Flask import error: {e}")
    raise

try:
    from flask_cors import CORS
except ImportError:
    CORS = None
    log.warning("Flask-CORS not available")

# ===================================================================
# Optional imports with graceful fallback
# ===================================================================
REDIS_AVAILABLE = False
GENAI_AVAILABLE = False
RAZORPAY_AVAILABLE = False

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    redis = None
    log.warning("Redis not available")

try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    genai = None
    log.warning("Google GenAI not available")

try:
    import razorpay
    RAZORPAY_AVAILABLE = True
except ImportError:
    razorpay = None
    log.warning("Razorpay not available")

# ===================================================================
# Simple Config (no complex classes)
# ===================================================================
def get_env(key, default=""):
    """Safely get environment variable."""
    try:
        return os.environ.get(key, default)
    except:
        return default

# Core config
SECRET_KEY = get_env("SECRET_KEY", secrets.token_urlsafe(32))
ADMIN_TOKEN = get_env("ADMIN_TOKEN", secrets.token_urlsafe(32))
FLASK_ENV = get_env("FLASK_ENV", "production")
IS_VERCEL = get_env("VERCEL", "false").lower() == "true"

# Redis
REDIS_URL = get_env("REDIS_URL") or get_env("UPSTASH_REDIS_URL") or get_env("KV_URL")
REDIS_TIMEOUT = int(get_env("REDIS_TIMEOUT", "5"))

# AI
GOOGLE_API_KEY = get_env("GOOGLE_API_KEY") or get_env("GEMINI_KEY") or ""
AI_MODEL = "gemini-2.0-flash"
AI_MAX_TOKENS = 200

# Payments
RAZORPAY_KEY_ID = get_env("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = get_env("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = get_env("RAZORPAY_WEBHOOK_SECRET", "")
PRO_AMOUNT = int(get_env("PRO_AMOUNT", "4900"))

# Limits
FREE_ASK_LIMIT = int(get_env("FREE_ASK_LIMIT", "10"))
MAX_XP_PER_UPDATE = int(get_env("MAX_XP_PER_UPDATE", "100000"))

# ===================================================================
# Simple Redis Client
# ===================================================================
class SimpleRedis:
    """Simple Redis client that doesn't fail."""
    
    def __init__(self):
        self.client = None
        if REDIS_AVAILABLE and REDIS_URL:
            try:
                self.client = redis.from_url(
                    REDIS_URL,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5
                )
                log.info("Redis connected")
            except Exception as e:
                log.error(f"Redis failed: {e}")
                self.client = None
    
    def get(self):
        return self.client
    
    def is_available(self):
        return self.client is not None

redis_client = SimpleRedis()

# ===================================================================
# Simple Storage (no complex threading)
# ===================================================================
class SimpleStorage:
    """Simple storage with memory fallback."""
    
    def __init__(self):
        self.users = {}
        self.leaderboard = {}
        self.ask_counts = defaultdict(int)
        self.total_asks = 0
        self.daily_active = defaultdict(set)
        self.leaderboard_cache = []
        self.leaderboard_ts = 0
        self.cache_ttl = 5
    
    def get_redis(self):
        return redis_client.get()
    
    def get_user(self, phone):
        """Get user by phone."""
        if not phone:
            return None
        
        r = self.get_redis()
        if r:
            try:
                data = r.hgetall(f"user:{phone}")
                if data:
                    return data
            except:
                pass
        
        return self.users.get(phone)
    
    def get_user_by_uid(self, uid):
        """Get user by UID."""
        r = self.get_redis()
        if r:
            try:
                phone = r.get(f"uid_to_phone:{uid}")
                if phone:
                    return self.get_user(phone)
            except:
                pass
        
        for user in self.users.values():
            if user.get("uid") == uid:
                return user
        return None
    
    def save_user(self, user_data):
        """Save user."""
        try:
            phone = user_data.get("phone")
            if not phone:
                return False
            
            r = self.get_redis()
            if r:
                try:
                    r.hset(f"user:{phone}", mapping=user_data)
                    r.expire(f"user:{phone}", 300)
                    r.set(f"uid_to_phone:{user_data.get('uid')}", phone, ex=300)
                except:
                    pass
            
            self.users[phone] = user_data
            return True
        except:
            return False
    
    def get_plan(self, phone):
        """Get user plan."""
        user = self.get_user(phone)
        return user.get("plan", "free") if user else "free"
    
    def update_plan(self, phone, plan):
        """Update user plan."""
        user = self.get_user(phone)
        if not user:
            user = {
                "phone": phone,
                "uid": secrets.token_urlsafe(16),
                "name": "Warrior",
                "plan": "free",
                "xp": 0,
                "level": 1
            }
        
        user["plan"] = plan
        user["updated_at"] = datetime.utcnow().isoformat()
        return self.save_user(user)
    
    def get_leaderboard(self, limit=10):
        """Get leaderboard."""
        now = time.time()
        
        if now - self.leaderboard_ts < self.cache_ttl and self.leaderboard_cache:
            return self.leaderboard_cache
        
        r = self.get_redis()
        entries = []
        
        if r:
            try:
                items = r.zrevrange("leaderboard", 0, limit - 1, withscores=True)
                for idx, (uid, score) in enumerate(items):
                    name = r.hget(f"user:{uid}", "name") or "Warrior"
                    level = int(r.hget(f"user:{uid}", "level") or 1)
                    entries.append({
                        "id": uid,
                        "name": name,
                        "xp": int(score),
                        "level": level,
                        "rank": idx + 1
                    })
            except:
                pass
        
        if not entries:
            # Memory fallback
            sorted_users = sorted(
                self.leaderboard.values(),
                key=lambda x: x.get("xp", 0),
                reverse=True
            )[:limit]
            entries = [
                {
                    "id": u.get("id"),
                    "name": u.get("name", "Warrior"),
                    "xp": u.get("xp", 0),
                    "level": u.get("level", 1),
                    "rank": i + 1
                }
                for i, u in enumerate(sorted_users)
            ]
        
        self.leaderboard_cache = entries
        self.leaderboard_ts = now
        return entries
    
    def update_leaderboard(self, uid, name, xp, phone=None, level=1):
        """Update leaderboard."""
        entry = {"id": uid, "name": name, "xp": xp, "level": level}
        
        r = self.get_redis()
        if r:
            try:
                r.zadd("leaderboard", {uid: xp})
                r.hset(f"user:{uid}", mapping={
                    "uid": uid,
                    "name": name,
                    "xp": xp,
                    "level": level
                })
                if phone:
                    r.hset(f"user:{uid}", "phone", phone)
            except:
                pass
        
        self.leaderboard[uid] = entry
        self.leaderboard_ts = 0  # Invalidate cache
    
    def increment_ask(self, uid):
        """Increment ask count."""
        r = self.get_redis()
        if r:
            try:
                new_count = r.hincrby("ask_counts", uid, 1)
                r.incr("total_asks")
                today = datetime.utcnow().strftime("%Y-%m-%d")
                r.sadd(f"daily_active:{today}", uid)
                return int(new_count)
            except:
                pass
        
        self.ask_counts[uid] = self.ask_counts.get(uid, 0) + 1
        self.total_asks += 1
        today = datetime.utcnow().strftime("%Y-%m-%d")
        self.daily_active[today].add(uid)
        return self.ask_counts[uid]
    
    def get_ask_count(self, uid):
        """Get ask count."""
        r = self.get_redis()
        if r:
            try:
                count = r.hget("ask_counts", uid)
                if count is not None:
                    return int(count)
            except:
                pass
        return self.ask_counts.get(uid, 0)
    
    def get_stats(self):
        """Get stats."""
        r = self.get_redis()
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
            except:
                pass
        
        return {
            "total_users": len(self.users),
            "total_asks": self.total_asks,
            "daily_active": len(self.daily_active.get(today, set())),
            "date": today,
            "redis": False
        }

# ===================================================================
# Simple AI Service
# ===================================================================
class SimpleAI:
    """Simple AI service."""
    
    def __init__(self):
        self.client = None
        if GENAI_AVAILABLE and GOOGLE_API_KEY:
            try:
                genai.configure(api_key=GOOGLE_API_KEY)
                self.client = genai.GenerativeModel(AI_MODEL)
                log.info("AI initialized")
            except:
                self.client = None
    
    def generate(self, question, name="Warrior", is_pro=False):
        """Generate response."""
        if not self.client:
            return "🔥 StudyGenie by Sparsh Singhal is loading! Give it a sec! 💪"
        
        try:
            prompt = f"""You are StudyGenie by Sparsh Singhal.
User: {name}
Tier: {"PRO" if is_pro else "FREE"}
Style: Hinglish, savage, encouraging, max 150 words.
Question: {question}
Response:"""
            
            response = self.client.generate_content(
                prompt,
                generation_config={
                    "max_output_tokens": AI_MAX_TOKENS,
                    "temperature": 0.8
                }
            )
            
            if response and response.text:
                text = response.text.strip()
                words = text.split()
                if len(words) > 150:
                    text = ' '.join(words[:150]) + "..."
                return text
            
            return "🔥 Sparsh Singhal's Genie is thinking! Try again! 💪"
            
        except:
            return "⚠️ Technical glitch! Try again - BY SPARSH SINGHAL"

# ===================================================================
# Simple Payment Service
# ===================================================================
class SimplePayment:
    """Simple payment service."""
    
    def __init__(self):
        self.client = None
        if RAZORPAY_AVAILABLE and RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
            try:
                self.client = razorpay.Client(
                    auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)
                )
                log.info("Razorpay initialized")
            except:
                self.client = None
    
    def create_order(self, uid, phone, name):
        """Create order."""
        if not self.client:
            return False, None, "Payment not configured"
        
        try:
            order = self.client.order.create({
                "amount": PRO_AMOUNT,
                "currency": "INR",
                "receipt": f"sg_{uid}_{int(time.time())}",
                "notes": {
                    "uid": uid,
                    "name": name,
                    "phone": phone
                }
            })
            
            return True, {
                "order_id": order["id"],
                "amount": order["amount"],
                "currency": order["currency"],
                "key_id": RAZORPAY_KEY_ID
            }, ""
        except Exception as e:
            log.error(f"Order creation failed: {e}")
            return False, None, str(e)
    
    def verify_webhook(self, payload, signature):
        """Verify webhook."""
        if not RAZORPAY_WEBHOOK_SECRET:
            return False
        
        expected = hmac.new(
            RAZORPAY_WEBHOOK_SECRET.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected, signature)
    
    def process_payment(self, payment_data):
        """Process payment."""
        try:
            notes = payment_data.get("notes", {})
            phone = notes.get("phone", "")
            uid = notes.get("uid", "")
            name = notes.get("name", "Warrior")
            
            if not phone or not uid:
                return False
            
            # Update user to PRO
            storage.update_plan(phone, "pro")
            
            # Update leaderboard
            user = storage.get_user(phone)
            if user:
                storage.update_leaderboard(
                    uid,
                    user.get("name", name),
                    user.get("xp", 0),
                    phone,
                    user.get("level", 1)
                )
            
            log.info(f"✅ PRO unlocked: {phone}")
            return True
        except Exception as e:
            log.error(f"Payment processing failed: {e}")
            return False

# ===================================================================
# Helper functions
# ===================================================================
def clean_phone(phone):
    """Clean phone number."""
    if not phone:
        return ""
    phone = re.sub(r'[^0-9]', '', str(phone))[:10]
    return phone if re.match(r"^\d{10}$", phone) else ""

def clean_name(name):
    """Clean name."""
    if not name:
        return "Warrior"
    return re.sub(r'[<>"\'\\]', '', str(name))[:50]

def clean_xp(xp):
    """Clean XP."""
    try:
        xp = int(xp)
    except:
        return 0
    return max(0, min(xp, MAX_XP_PER_UPDATE))

def generate_uid():
    """Generate UID."""
    return secrets.token_urlsafe(16)

# ===================================================================
# Initialize services
# ===================================================================
storage = SimpleStorage()
ai_service = SimpleAI()
payment_service = SimplePayment()

# ===================================================================
# Create Flask app
# ===================================================================
app = Flask(__name__)
app.secret_key = SECRET_KEY

# CORS
if CORS:
    CORS(app, resources={r"/*": {"origins": "*"}})

# ===================================================================
# Admin decorator
# ===================================================================
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

# ===================================================================
# Routes
# ===================================================================
@app.route("/")
def home():
    """Home page."""
    return HTML_PAGE

@app.route("/sparsh.jpg")
def photo():
    """Photo."""
    try:
        return send_from_directory(".", "sparsh.jpg")
    except:
        return "", 204

@app.route("/register_user", methods=["POST"])
def register_user():
    """Register user."""
    try:
        data = request.get_json(silent=True) or {}
        phone = clean_phone(data.get("phone"))
        name = clean_name(data.get("name", "Warrior"))
        uid = data.get("uid") or generate_uid()
        
        if not phone:
            return jsonify({"error": "Valid phone required"}), 400
        
        user = storage.get_user(phone)
        if user:
            return jsonify({
                "ok": True,
                "uid": user.get("uid"),
                "name": user.get("name"),
                "phone": user.get("phone"),
                "plan": user.get("plan", "free")
            })
        
        user_data = {
            "phone": phone,
            "uid": uid,
            "name": name,
            "plan": "free",
            "xp": 0,
            "level": 1,
            "created_at": datetime.utcnow().isoformat()
        }
        
        if storage.save_user(user_data):
            storage.update_leaderboard(uid, name, 0, phone, 1)
            return jsonify({
                "ok": True,
                "uid": uid,
                "name": name,
                "phone": phone,
                "plan": "free"
            })
        
        return jsonify({"error": "Failed to save"}), 500
    except Exception as e:
        log.error(f"Register error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/leaderboard")
def get_leaderboard():
    """Get leaderboard."""
    try:
        limit = min(int(request.args.get("limit", 10)), 100)
        entries = storage.get_leaderboard(limit)
        return jsonify(entries)
    except:
        return jsonify([]), 200

@app.route("/update_xp", methods=["POST"])
def update_xp():
    """Update XP."""
    try:
        data = request.get_json(silent=True) or {}
        uid = str(data.get("uid", ""))[:64]
        xp = clean_xp(data.get("xp", 0))
        phone = clean_phone(data.get("phone"))
        name = clean_name(data.get("name", "Warrior"))
        
        if not uid:
            return jsonify({"error": "UID required"}), 400
        
        level = 1 + (xp // 100) if xp > 0 else 1
        storage.update_leaderboard(uid, name, xp, phone, level)
        
        return jsonify({"ok": True, "level": level})
    except:
        return jsonify({"ok": True}), 200

@app.route("/ask", methods=["POST"])
def ask():
    """Ask question."""
    try:
        data = request.get_json(silent=True) or {}
        question = (data.get("q") or "").strip()[:2000]
        name = clean_name(data.get("name", "Warrior"))
        uid = str(data.get("uid", "anon"))[:64]
        phone = clean_phone(data.get("phone"))
        
        if not question:
            return jsonify({"error": "Empty question"}), 400
        
        # Check quota
        plan = storage.get_plan(phone) if phone else "free"
        used = storage.get_ask_count(uid)
        
        if plan == "free" and used >= FREE_ASK_LIMIT:
            return jsonify({
                "limit_reached": True,
                "ans": f"""🚀 AMMO KHATAM! 🔫

Oye {name}! Free ammo over!

💎 RELOAD - ₹49 Only!
✅ Unlimited Questions

Click RELOAD button below!

- BY SPARSH SINGHAL"""
            }), 402
        
        # Generate response
        response = ai_service.generate(question, name, plan == "pro")
        
        # Update stats
        storage.increment_ask(uid)
        
        # Update XP
        user = storage.get_user(phone) if phone else None
        xp_gained = 0
        if user:
            xp_gained = 25 if plan == "pro" else 10
            user["xp"] = user.get("xp", 0) + xp_gained
            if user["xp"] >= user.get("level", 1) * 100:
                user["level"] = user.get("level", 1) + 1
            storage.save_user(user)
            storage.update_leaderboard(
                uid,
                user.get("name", name),
                user.get("xp", 0),
                phone,
                user.get("level", 1)
            )
        
        return jsonify({
            "ans": response,
            "xp_gained": xp_gained
        })
    except Exception as e:
        log.error(f"Ask error: {e}")
        return jsonify({"ans": "⚠️ Try again! - BY SPARSH SINGHAL"}), 500

@app.route("/create_order", methods=["POST"])
def create_order():
    """Create order."""
    try:
        data = request.get_json(silent=True) or {}
        phone = clean_phone(data.get("phone"))
        name = clean_name(data.get("name", "Warrior"))
        uid = str(data.get("uid", ""))[:64]
        
        if not phone:
            return jsonify({"error": "Phone required"}), 400
        if not uid:
            return jsonify({"error": "UID required"}), 400
        
        success, result, error = payment_service.create_order(uid, phone, name)
        
        if success:
            return jsonify(result)
        return jsonify({"error": error}), 500
    except Exception as e:
        log.error(f"Order error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/razorpay/webhook", methods=["POST"])
def webhook():
    """Webhook."""
    try:
        payload = request.get_data()
        signature = request.headers.get("X-Razorpay-Signature", "")
        
        if not payment_service.verify_webhook(payload, signature):
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
    """Check plan."""
    try:
        data = request.get_json(silent=True) or {}
        phone = clean_phone(data.get("phone"))
        plan = storage.get_plan(phone) if phone else "free"
        return jsonify({"plan": plan})
    except:
        return jsonify({"plan": "free"}), 200

@app.route("/admin/stats")
@admin_required
def admin_stats():
    """Admin stats."""
    try:
        stats = storage.get_stats()
        return jsonify(stats)
    except:
        return jsonify({"error": "Stats error"}), 500

@app.route("/admin/users")
@admin_required
def admin_users():
    """Admin users."""
    try:
        users = list(storage.users.values())[:100]
        return jsonify({"users": users, "total": len(users)})
    except:
        return jsonify({"users": [], "total": 0}), 200

@app.route("/admin/force_pro", methods=["POST"])
@admin_required
def admin_force_pro():
    """Force PRO."""
    try:
        data = request.get_json(silent=True) or {}
        phone = clean_phone(data.get("phone"))
        
        if not phone:
            return jsonify({"error": "Phone required"}), 400
        
        if storage.update_plan(phone, "pro"):
            return jsonify({"ok": True, "phone": phone, "plan": "pro"})
        return jsonify({"error": "Failed"}), 500
    except:
        return jsonify({"error": "Failed"}), 500

# ===================================================================
# HTML (minimal version)
# ===================================================================
HTML_PAGE = """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>StudyGenie 🚀</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
<style>
body{background:#050507;color:#fff;font-family:sans-serif}
.hud{background:rgba(17,17,19,0.96);border:1px solid #232326;border-radius:16px;padding:20px}
.bubble-ai{background:#17171a;border-left:4px solid #ff4d00;border-radius:4px 16px 16px 16px;padding:16px}
.bubble-user{background:#fff;color:#000;border-radius:14px 14px 2px 14px;padding:10px 16px;font-weight:900}
.ammo{width:42px;height:52px;background:#121216;border:1px solid #2e2e33;border-radius:6px;display:inline-flex;align-items:center;justify-content:center;margin:2px}
.ammo.used{opacity:.15}
.progress{height:12px;background:#0f0f11;border:1px solid #2a2a2e;border-radius:2px;overflow:hidden}
.progress>div{height:100%;background:linear-gradient(90deg,#ff4d00,#ff8a00)}
#chat{max-height:60vh;overflow-y:auto}
.btn-fire{background:linear-gradient(90deg,#ff4d00,#ff8a00);border:none;padding:10px 24px;border-radius:10px;font-weight:900;cursor:pointer}
input{background:#0f0f11;border:2px solid #2a2a2e;border-radius:10px;padding:12px;color:#fff;outline:none}
input:focus{border-color:#ff4d00}
</style>
</head>
<body>
<div class="max-w-[1500px] mx-auto p-4">
<div class="hud flex justify-between items-center">
<div>
<h1 class="text-2xl font-black">STUDYGENIE <span style="color:#ff4d00">⚔️</span></h1>
<p style="color:#ff8a00">BY SPARSH SINGHAL</p>
<div class="flex items-center gap-3 mt-2">
<span>XP</span>
<div class="progress w-40"><div id="xpBar" style="width:0%"></div></div>
<span id="xpText">0/100</span>
</div>
<p>LVL <span id="lvl">1</span> | <span id="userName">WARRIOR</span></p>
</div>
<div class="text-right">
<div style="font-size:10px;color:#666">AMMO</div>
<div style="font-size:28px;font-weight:900"><span id="ammoLeft">10</span>/10</div>
</div>
</div>

<div class="grid grid-cols-12 gap-4 mt-4">
<div class="col-span-12 lg:col-span-3">
<div class="hud">
<p style="color:#666;font-size:10px">🎯 MISSIONS</p>
<div class="bg-black p-3 rounded mt-2 border-l-4 border-[#ff4d00]">
<div class="flex justify-between"><span>💪 3 DOUBTS</span><span id="q1">0/3</span></div>
<div class="progress mt-1"><div id="q1b" style="width:0%"></div></div>
</div>
</div>
<div class="hud mt-3">
<p style="color:#666;font-size:10px">🔫 AMMO CRATE</p>
<div id="lamps" class="mt-2"></div>
<button onclick="openPay()" class="btn-fire w-full mt-3">💎 RELOAD - ₹49</button>
</div>
<div class="hud mt-3">
<p style="color:#ff4d00;font-size:10px;font-weight:900">🏆 LEADERBOARD</p>
<div id="board" class="mt-2"></div>
</div>
</div>

<div class="col-span-12 lg:col-span-9">
<div class="hud" style="min-height:400px">
<div id="chat"></div>
<div class="mt-4 flex gap-2">
<input id="q" class="flex-1" placeholder="🔥 ASK YOUR DOUBT..." onkeypress="if(event.key==='Enter')ask()">
<button onclick="ask()" class="btn-fire">🔫 FIRE</button>
</div>
</div>
</div>
</div>
</div>

<!-- Onboard -->
<div id="onboard" style="position:fixed;inset:0;background:rgba(0,0,0,0.95);display:flex;align-items:center;justify-content:center;z-index:999">
<div class="hud" style="max-width:400px;width:100%">
<h2 class="text-2xl font-black">⚔️ REGISTER</h2>
<p style="color:#ff8a00;font-size:12px">BY SPARSH SINGHAL</p>
<div class="mt-4 space-y-3">
<input id="inpName" class="w-full" placeholder="Your Name" maxlength="20">
<input id="inpPhone" class="w-full" placeholder="10 digit phone" maxlength="10" type="tel">
</div>
<button onclick="register()" class="btn-fire w-full mt-4">🔥 ENTER</button>
</div>
</div>

<script>
// State
let userId = localStorage.getItem('uid') || 'user_' + Math.random().toString(36).substr(2,9);
localStorage.setItem('uid', userId);
let name = localStorage.getItem('name') || '';
let phone = localStorage.getItem('phone') || '';
let isPro = localStorage.getItem('pro') === 'true';
let stats = JSON.parse(localStorage.getItem('stats') || '{"xp":0,"level":1,"wishes":0,"q1":0}');

// Check onboard
if(name && phone && phone.length==10){
document.getElementById('onboard').style.display='none';
document.getElementById('userName').textContent=name.toUpperCase();
} else {
document.getElementById('onboard').style.display='flex';
}

function register(){
let n = document.getElementById('inpName').value.trim();
let p = document.getElementById('inpPhone').value.trim().replace(/[^0-9]/g,'');
if(n.length<2 || p.length!=10) return alert('Name and 10 digit phone required');
name=n; phone=p;
localStorage.setItem('name', name);
localStorage.setItem('phone', phone);
document.getElementById('onboard').style.display='none';
document.getElementById('userName').textContent=name.toUpperCase();
fetch('/register_user', {
method:'POST',
headers:{'Content-Type':'application/json'},
body:JSON.stringify({uid:userId, name, phone})
});
checkPlan();
render();
}

function render(){
document.getElementById('ammoLeft').textContent = isPro ? '∞' : (10 - stats.wishes);
document.getElementById('lvl').textContent = stats.level;
document.getElementById('xpBar').style.width = stats.xp + '%';
document.getElementById('xpText').textContent = stats.xp + '/100';
document.getElementById('q1').textContent = stats.q1 + '/3';
document.getElementById('q1b').style.width = (stats.q1/3*100) + '%';
// Lamps
let html = '';
for(let i=0;i<10;i++){
let used = i < stats.wishes && !isPro;
html += `<div class="ammo${used?' used':''}">${used?'💨':'🪔'}</div>`;
}
document.getElementById('lamps').innerHTML = html;
}

function save(){ localStorage.setItem('stats', JSON.stringify(stats)); render(); }

async function checkPlan(){
try{
let r = await fetch('/check_plan', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({phone})});
let d = await r.json();
if(d.plan==='pro'){ isPro=true; localStorage.setItem('pro','true'); render(); }
}catch{}
}

async function loadBoard(){
try{
let r = await fetch('/leaderboard');
let d = await r.json();
let html = d.map((u,i) => 
`<div style="display:flex;justify-content:space-between;padding:6px;background:#000;margin:4px 0;border-radius:6px;border:1px solid ${u.id===userId?'#ff4d00':'#222'}">
<span>${i+1}. ${u.name} ${u.id===userId?'⭐':''}</span>
<span style="color:#ff4d00">${u.xp}XP</span>
</div>`
).join('');
document.getElementById('board').innerHTML = html || '<div style="color:#666;text-align:center">No warriors yet</div>';
}catch{}
}

function appendBubble(text, isUser){
let chat = document.getElementById('chat');
let div = document.createElement('div');
div.className = isUser ? 'text-right mb-3' : 'mb-3';
div.innerHTML = `<div class="${isUser?'bubble-user inline-block':'bubble-ai'}">${text}</div>`;
chat.appendChild(div);
chat.scrollTop = chat.scrollHeight;
}

async function ask(){
if(!name || !phone) return document.getElementById('onboard').style.display='flex';
let q = document.getElementById('q').value.trim();
if(!q) return;
appendBubble(q, true);
document.getElementById('q').value = '';
appendBubble('⏳ Genie thinking...', false);

try{
let res = await fetch('/ask', {
method:'POST',
headers:{'Content-Type':'application/json'},
body:JSON.stringify({q, name, phone, uid:userId})
});
let data = await res.json();
document.getElementById('chat').lastChild.remove();

if(res.status==402 || data.limit_reached){
appendBubble(data.ans, false);
setTimeout(openPay, 2000);
return;
}

stats.wishes++;
stats.q1 = Math.min(3, stats.q1+1);
stats.xp += 12;
if(stats.xp>=100){ stats.level++; stats.xp=0; appendBubble('🔥 LEVEL UP!', false); }
save();
appendBubble(data.ans, false);
}catch(e){
document.getElementById('chat').lastChild.remove();
appendBubble('⚠️ Try again! - BY SPARSH SINGHAL', false);
}
}

async function openPay(){
if(!phone || phone.length!=10) return alert('Register first!');
try{
let res = await fetch('/create_order', {
method:'POST',
headers:{'Content-Type':'application/json'},
body:JSON.stringify({uid:userId, name, phone})
});
let order = await res.json();
if(order.error) return alert(order.error);

const options = {
key: order.key_id,
amount: order.amount,
currency: order.currency,
name: "StudyGenie Pro",
order_id: order.order_id,
prefill: {name, contact: phone},
theme: {color:"#ff4d00"},
handler: function(){
alert('✅ PRO UNLOCKED!');
localStorage.setItem('pro','true');
isPro=true;
render();
location.reload();
}
};
new Razorpay(options).open();
}catch(e){ alert('Error: '+e.message); }
}

// Init
render();
checkPlan();
loadBoard();
setInterval(loadBoard, 5000);

document.getElementById('chat').innerHTML = `
<div class="mb-3">
<div class="bubble-ai">
🔥 <b>Welcome to StudyGenie by Sparsh Singhal!</b><br><br>
Ask your doubts, get savage answers! 💪<br>
<span style="color:#ff8a00;font-size:10px">BY SPARSH SINGHAL</span>
</div>
</div>
`;
</script>
</body></html>
"""

# ===================================================================
# Vercel Handler
# ===================================================================
def handler(request, context):
    """Vercel serverless handler."""
    return app(request, context)

# ===================================================================
# Local Development
# ===================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

# ===================================================================
# END OF FILE
# ===================================================================
