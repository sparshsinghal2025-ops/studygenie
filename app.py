# ===================================================================
# STUDYGENIE - FINAL WORKING VERSION 🔥
# By Sparsh Singhal - Registration Fixed + AI Working
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

# ===================================================================
# Logging
# ===================================================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger("studygenie")

# ===================================================================
# Flask
# ===================================================================
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

# Optional imports
try:
    import redis
    REDIS_AVAILABLE = True
except:
    REDIS_AVAILABLE = False
    redis = None

try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except:
    GENAI_AVAILABLE = False
    genai = None

try:
    import razorpay
    RAZORPAY_AVAILABLE = True
except:
    RAZORPAY_AVAILABLE = False
    razorpay = None

# ===================================================================
# Config
# ===================================================================
SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_urlsafe(32))
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", secrets.token_urlsafe(32))
REDIS_URL = os.environ.get("REDIS_URL") or os.environ.get("UPSTASH_REDIS_URL") or os.environ.get("KV_URL")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_KEY") or ""
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
FREE_ASK_LIMIT = int(os.environ.get("FREE_ASK_LIMIT", "10"))
PRO_AMOUNT = int(os.environ.get("PRO_AMOUNT", "4900"))

# ===================================================================
# Redis Client
# ===================================================================
class RedisClient:
    def __init__(self):
        self.client = None
        if REDIS_AVAILABLE and REDIS_URL:
            try:
                self.client = redis.from_url(REDIS_URL, decode_responses=True)
                log.info("✅ Redis connected")
            except:
                pass
    
    def get(self):
        return self.client

redis_client = RedisClient()

# ===================================================================
# Storage
# ===================================================================
class Storage:
    def __init__(self):
        self.users = {}
        self.leaderboard = {}
        self.ask_counts = defaultdict(int)
        self.total_asks = 0
        self.cache_ts = 0
        self.cache_data = []
    
    def get_redis(self):
        return redis_client.get()
    
    def get_user(self, phone):
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
    
    def save_user(self, data):
        try:
            phone = data.get("phone")
            if not phone:
                return False
            r = self.get_redis()
            if r:
                try:
                    r.hset(f"user:{phone}", mapping=data)
                    r.expire(f"user:{phone}", 86400)
                    r.set(f"uid_to_phone:{data.get('uid')}", phone, ex=86400)
                except:
                    pass
            self.users[phone] = data
            return True
        except:
            return False
    
    def get_plan(self, phone):
        user = self.get_user(phone)
        return user.get("plan", "free") if user else "free"
    
    def update_plan(self, phone, plan):
        user = self.get_user(phone)
        if not user:
            user = {"phone": phone, "uid": secrets.token_urlsafe(16), "name": "Warrior", "plan": "free", "xp": 0, "level": 1}
        user["plan"] = plan
        user["updated_at"] = datetime.utcnow().isoformat()
        return self.save_user(user)
    
    def get_leaderboard(self, limit=10):
        now = time.time()
        if now - self.cache_ts < 5 and self.cache_data:
            return self.cache_data
        
        r = self.get_redis()
        entries = []
        if r:
            try:
                items = r.zrevrange("leaderboard", 0, limit-1, withscores=True)
                for idx, (uid, score) in enumerate(items):
                    name = r.hget(f"user:{uid}", "name") or "Warrior"
                    level = int(r.hget(f"user:{uid}", "level") or 1)
                    entries.append({"id": uid, "name": name, "xp": int(score), "level": level, "rank": idx+1})
            except:
                pass
        
        if not entries:
            sorted_users = sorted(self.leaderboard.values(), key=lambda x: x.get("xp", 0), reverse=True)[:limit]
            entries = [{"id": u.get("id"), "name": u.get("name", "Warrior"), "xp": u.get("xp", 0), "level": u.get("level", 1), "rank": i+1} for i, u in enumerate(sorted_users)]
        
        self.cache_data = entries
        self.cache_ts = now
        return entries
    
    def update_leaderboard(self, uid, name, xp, phone=None, level=1):
        r = self.get_redis()
        if r:
            try:
                r.zadd("leaderboard", {uid: xp})
                r.hset(f"user:{uid}", mapping={"uid": uid, "name": name, "xp": xp, "level": level})
                if phone:
                    r.hset(f"user:{uid}", "phone", phone)
            except:
                pass
        self.leaderboard[uid] = {"id": uid, "name": name, "xp": xp, "level": level}
        self.cache_ts = 0
    
    def increment_ask(self, uid):
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
        return self.ask_counts[uid]
    
    def get_ask_count(self, uid):
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
            "daily_active": 0,
            "date": today,
            "redis": False
        }

storage = Storage()

# ===================================================================
# AI SERVICE
# ===================================================================
class AIService:
    def __init__(self):
        self.client = None
        if GENAI_AVAILABLE and GOOGLE_API_KEY:
            try:
                genai.configure(api_key=GOOGLE_API_KEY)
                self.client = genai.GenerativeModel("gemini-2.0-flash")
                log.info("✅ Gemini AI initialized")
            except Exception as e:
                log.error(f"Gemini init failed: {e}")
    
    def generate(self, question, name="Warrior", is_pro=False):
        if not self.client:
            return f"""⚠️ AI Service Not Configured

Oye {name}! Please set GOOGLE_API_KEY in environment variables.

- BY SPARSH SINGHAL"""
        
        try:
            prompt = f"""You are StudyGenie by Sparsh Singhal. User: {name}. 
Question: {question}

Give a complete, accurate answer. Show steps for numericals.
Use Hinglish + English. Be helpful and encouraging.

Response:"""
            
            response = self.client.generate_content(
                prompt,
                generation_config={
                    "max_output_tokens": 500,
                    "temperature": 0.7
                }
            )
            
            if response and response.text:
                return response.text.strip()
            
            return f"⚠️ Could not generate response. Please try again.\n\n- BY SPARSH SINGHAL"
            
        except Exception as e:
            log.error(f"AI error: {e}")
            return f"""⚠️ Error: {str(e)}

Please try again or rephrase your question.

- BY SPARSH SINGHAL"""

ai_service = AIService()

# ===================================================================
# Payment Service
# ===================================================================
class PaymentService:
    def __init__(self):
        self.client = None
        if RAZORPAY_AVAILABLE and RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
            try:
                self.client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
                log.info("✅ Razorpay initialized")
            except:
                pass
    
    def create_order(self, uid, phone, name):
        if not self.client:
            return False, None, "Payment not configured"
        try:
            order = self.client.order.create({
                "amount": PRO_AMOUNT,
                "currency": "INR",
                "receipt": f"sg_{uid}_{int(time.time())}",
                "notes": {"uid": uid, "name": name, "phone": phone}
            })
            return True, {"order_id": order["id"], "amount": order["amount"], "currency": order["currency"], "key_id": RAZORPAY_KEY_ID}, ""
        except Exception as e:
            log.error(f"Order error: {e}")
            return False, None, str(e)
    
    def verify_webhook(self, payload, signature):
        if not RAZORPAY_WEBHOOK_SECRET:
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
            log.info(f"✅ PRO unlocked: {phone}")
            return True
        except Exception as e:
            log.error(f"Payment process error: {e}")
            return False

payment_service = PaymentService()

# ===================================================================
# Helpers
# ===================================================================
def clean_phone(p):
    if not p:
        return ""
    p = re.sub(r'[^0-9]', '', str(p))[:10]
    return p if re.match(r"^\d{10}$", p) else ""

def clean_name(n):
    if not n:
        return "Warrior"
    return re.sub(r'[<>"\'\\]', '', str(n))[:50]

def clean_xp(x):
    try:
        return max(0, min(int(x), 100000))
    except:
        return 0

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
    except:
        return "", 204

@app.route("/register_user", methods=["POST"])
def register_user():
    try:
        data = request.get_json(silent=True) or {}
        phone = clean_phone(data.get("phone"))
        name = clean_name(data.get("name", "Warrior"))
        uid = data.get("uid") or generate_uid()
        
        if not phone:
            return jsonify({"error": "Valid 10-digit phone required"}), 400
        
        existing = storage.get_user(phone)
        if existing:
            return jsonify({
                "ok": True,
                "uid": existing.get("uid"),
                "name": existing.get("name"),
                "phone": existing.get("phone"),
                "plan": existing.get("plan", "free")
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
            log.info(f"✅ User registered: {phone} - {name}")
            return jsonify({
                "ok": True,
                "uid": uid,
                "name": name,
                "phone": phone,
                "plan": "free"
            })
        
        return jsonify({"error": "Failed to save user"}), 500
    except Exception as e:
        log.error(f"Register error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/leaderboard")
def get_leaderboard():
    try:
        limit = min(int(request.args.get("limit", 10)), 100)
        return jsonify(storage.get_leaderboard(limit))
    except:
        return jsonify([]), 200

@app.route("/update_xp", methods=["POST"])
def update_xp():
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
    try:
        start_time = time.time()
        data = request.get_json(silent=True) or {}
        question = (data.get("q") or "").strip()[:2000]
        name = clean_name(data.get("name", "Warrior"))
        uid = str(data.get("uid", "anon"))[:64]
        phone = clean_phone(data.get("phone"))
        
        if not question:
            return jsonify({"error": "Empty question"}), 400
        
        plan = storage.get_plan(phone) if phone else "free"
        used = storage.get_ask_count(uid)
        
        if plan == "free" and used >= FREE_ASK_LIMIT:
            return jsonify({
                "limit_reached": True,
                "ans": f"""🚀 AMMO KHATAM! 🔫

Oye {name}! Your free ammo is over!

💎 RELOAD NOW - ₹49 Only!
Click the "RELOAD" button below!

- BY SPARSH SINGHAL"""
            }), 402
        
        response = ai_service.generate(question, name, plan == "pro")
        
        storage.increment_ask(uid)
        
        user = storage.get_user(phone) if phone else None
        xp_gained = 0
        level_up = False
        
        if user:
            xp_gained = 25 if plan == "pro" else 10
            user["xp"] = user.get("xp", 0) + xp_gained
            
            if user["xp"] >= user.get("level", 1) * 100:
                user["level"] = user.get("level", 1) + 1
                level_up = True
            
            storage.save_user(user)
            storage.update_leaderboard(
                uid,
                user.get("name", name),
                user.get("xp", 0),
                phone,
                user.get("level", 1)
            )
        
        elapsed = time.time() - start_time
        log.info(f"⚡ Ask completed in {elapsed:.2f}s")
        
        return jsonify({
            "ans": response,
            "xp_gained": xp_gained,
            "level_up": level_up,
            "level": user.get("level", 1) if user else 1
        })
        
    except Exception as e:
        log.error(f"Ask error: {e}")
        return jsonify({"ans": "⚠️ Try again! - BY SPARSH SINGHAL"}), 500

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
        
        success, result, error = payment_service.create_order(uid, phone, name)
        
        if success:
            return jsonify(result)
        return jsonify({"error": error}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/razorpay/webhook", methods=["POST"])
def webhook():
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
        return jsonify({"error": str(e)}), 500

@app.route("/check_plan", methods=["POST"])
def check_plan():
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
    try:
        return jsonify(storage.get_stats())
    except:
        return jsonify({"error": "Stats error"}), 500

@app.route("/admin/users")
@admin_required
def admin_users():
    try:
        users = list(storage.users.values())[:100]
        return jsonify({"users": users, "total": len(users)})
    except:
        return jsonify({"users": [], "total": 0}), 200

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
    except:
        return jsonify({"error": "Failed"}), 500

# ===================================================================
# HTML - REGISTRATION WORKING 🔥
# ===================================================================
HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>StudyGenie 🔥</title>
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
</style>
</head>
<body>

<!-- Onboard Modal -->
<div id="onboard" style="position:fixed;inset:0;background:rgba(0,0,0,0.97);display:flex;align-items:center;justify-content:center;z-index:999;backdrop-filter:blur(10px)">
  <div class="hud max-w-[420px] w-full">
    <div class="flex items-center gap-4">
      <img src="/sparsh.jpg" class="w-16 h-16 rounded-xl border-2 border-[#ff4d00] object-cover">
      <div>
        <h2 class="text-2xl font-black">🔥 REGISTER</h2>
        <p class="text-[#ff8a00] text-sm font-bold">BY SPARSH SINGHAL</p>
      </div>
    </div>
    <p class="text-sm text-zinc-400 mt-3">Enter the battlefield, warrior!</p>
    <div class="mt-4 space-y-3">
      <input id="inpName" class="w-full bg-black border-2 border-zinc-800 rounded-xl px-4 py-3 text-white outline-none input-glow" placeholder="⚡ Your Name" maxlength="20">
      <input id="inpPhone" class="w-full bg-black border-2 border-zinc-800 rounded-xl px-4 py-3 text-white outline-none input-glow" placeholder="📱 10 digit phone" maxlength="10" type="tel">
    </div>
    <button onclick="registerUser()" class="btn-fire w-full mt-4" id="registerBtn">🔥 ENTER BATTLEFIELD</button>
    <p id="registerStatus" class="text-xs text-zinc-500 mt-2 text-center"></p>
  </div>
</div>

<!-- Main App -->
<div id="app" style="display:none;max-width:1500px;margin:0 auto;padding:16px">
  <div class="hud flex justify-between items-center sticky top-2 z-30">
    <div class="flex items-center gap-6">
      <img src="/sparsh.jpg" class="w-24 h-24 rounded-[16px] border-4 border-[#ff4d00] object-cover cursor-pointer">
      <div>
        <h1 class="text-2xl font-black tracking-wider">STUDYGENIE <span class="text-[#ff4d00]">🔥</span></h1>
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
      <div class="text-right">
        <div class="text-xs text-zinc-500 tracking-widest">🔥 AMMO</div>
        <div class="text-3xl font-black"><span id="ammoLeft">10</span>/10</div>
      </div>
      <div class="w-px h-12 bg-zinc-800"></div>
      <div class="text-right">
        <div class="text-xs text-zinc-500 tracking-widest">💎 PLAN</div>
        <div id="planDisplay" class="font-bold text-[#ff8a00]">FREE</div>
      </div>
    </div>
  </div>

  <div class="grid grid-cols-12 gap-4 mt-4">
    <div class="col-span-12 lg:col-span-3 space-y-4">
      <div class="hud">
        <p class="text-xs text-zinc-500 tracking-widest">🎯 MISSIONS</p>
        <div class="bg-black p-3 rounded mt-2 border-l-4 border-[#ff4d00]">
          <div class="flex justify-between text-sm font-bold"><span>💪 3 DOUBTS</span><span id="q1">0/3</span></div>
          <div class="progress mt-1"><div id="q1b" style="width:0%"></div></div>
        </div>
        <div class="bg-black p-3 rounded mt-2 border-l-4 border-[#ff8a00]">
          <div class="flex justify-between text-sm font-bold"><span>🔥 10 QUESTIONS</span><span id="q2">0/10</span></div>
          <div class="progress mt-1"><div id="q2b" style="width:0%"></div></div>
        </div>
      </div>

      <div class="hud">
        <p class="text-xs text-zinc-500 tracking-widest">🔫 AMMO CRATE</p>
        <div id="lamps" class="mt-2"></div>
        <button onclick="openPay()" class="btn-fire w-full mt-3 text-sm">💎 RELOAD - ₹49</button>
      </div>

      <div class="hud">
        <p class="text-xs text-[#ff4d00] tracking-widest font-black">🏆 LEADERBOARD</p>
        <div id="board" class="mt-2 space-y-1"></div>
        <div class="mt-2 text-xs text-zinc-500 bg-black p-2 rounded border border-zinc-800">
          <span class="text-[#ff8a00]">🔒 PRIVATE</span><br>
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
          <input id="q" class="flex-1 bg-black border-2 border-zinc-800 rounded-xl px-4 py-3 text-white outline-none input-glow" placeholder="🔥 ANY QUESTION... I'll solve it!" onkeypress="if(event.key==='Enter')ask()">
          <button onclick="ask()" class="btn-fire">🔫 ASK</button>
        </div>
        <div class="mt-2 flex justify-between text-xs text-zinc-500">
          <span>💡 10 free questions, then ₹49 for unlimited!</span>
          <span>❤️ By Sparsh Singhal</span>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
// ============================================================
// STATE - USING appData NOT localStorage directly
// ============================================================
const STORAGE_KEY = 'studygenie_data';
let appData = {
  userId: 'user_' + Math.random().toString(36).substr(2,9),
  name: '',
  phone: '',
  isPro: false,
  stats: { xp: 0, level: 1, wishes: 0, q1: 0, q2: 0, totalXp: 0 }
};

function loadData() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      const data = JSON.parse(saved);
      appData = { ...appData, ...data };
      console.log('✅ Data loaded:', appData);
    }
  } catch(e) {}
}

function saveData() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(appData));
    console.log('✅ Data saved');
  } catch(e) {}
}

loadData();

// ============================================================
// AUDIO
// ============================================================
let audioCtx = null;
function playSound(type) {
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    gain.gain.setValueAtTime(0.2, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.15);
    osc.start();
    osc.stop(audioCtx.currentTime + 0.15);
  } catch(e) {}
}

// ============================================================
// REGISTRATION - FIXED ✅
// ============================================================
function registerUser() {
  console.log('📝 Register button clicked!');
  
  const nameInput = document.getElementById('inpName');
  const phoneInput = document.getElementById('inpPhone');
  const statusEl = document.getElementById('registerStatus');
  const btn = document.getElementById('registerBtn');
  
  const name = nameInput.value.trim();
  const phone = phoneInput.value.trim().replace(/[^0-9]/g, '');
  
  console.log('📝 Name:', name, 'Phone:', phone);
  
  if (!name || name.length < 2) {
    statusEl.textContent = '⚠️ Please enter your name!';
    statusEl.style.color = '#ff4444';
    playSound('empty');
    return;
  }
  
  if (!phone || phone.length !== 10) {
    statusEl.textContent = '📱 Please enter a valid 10-digit phone number!';
    statusEl.style.color = '#ff4444';
    playSound('empty');
    return;
  }
  
  statusEl.textContent = '⏳ Registering...';
  statusEl.style.color = '#ff8a00';
  btn.disabled = true;
  btn.textContent = '⏳ WAIT...';
  
  // Save to appData
  appData.name = name;
  appData.phone = phone;
  saveData();
  
  console.log('📡 Sending to server:', {uid: appData.userId, name, phone});
  
  fetch('/register_user', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      uid: appData.userId,
      name: name,
      phone: phone
    })
  })
  .then(res => res.json())
  .then(data => {
    console.log('✅ Server response:', data);
    if (data.ok) {
      statusEl.textContent = '✅ Welcome ' + name + '!';
      statusEl.style.color = '#44ff88';
      playSound('level');
      setTimeout(() => {
        document.getElementById('onboard').style.display = 'none';
        document.getElementById('app').style.display = 'block';
        initApp();
      }, 500);
    } else {
      statusEl.textContent = '❌ ' + (data.error || 'Registration failed');
      statusEl.style.color = '#ff4444';
      btn.disabled = false;
      btn.textContent = '🔥 ENTER BATTLEFIELD';
    }
  })
  .catch(err => {
    console.error('❌ Registration error:', err);
    statusEl.textContent = '❌ Network error. Please try again.';
    statusEl.style.color = '#ff4444';
    btn.disabled = false;
    btn.textContent = '🔥 ENTER BATTLEFIELD';
  });
}

// ============================================================
// APP INIT
// ============================================================
function initApp() {
  console.log('🚀 Initializing app...');
  document.getElementById('userName').textContent = appData.name.toUpperCase();
  document.getElementById('myId').textContent = '🆔 ' + appData.userId;
  document.getElementById('myPhone').textContent = '📱 ' + appData.phone.slice(0,2) + '******' + appData.phone.slice(-2);
  render();
  loadBoard();
  checkPlan();
  setInterval(loadBoard, 10000);
}

function render() {
  const s = appData.stats;
  document.getElementById('ammoLeft').textContent = appData.isPro ? '∞' : (10 - s.wishes);
  document.getElementById('lvl').textContent = s.level;
  document.getElementById('xpBar').style.width = s.xp + '%';
  document.getElementById('xpText').textContent = s.xp + '/100';
  document.getElementById('q1').textContent = s.q1 + '/3';
  document.getElementById('q1b').style.width = (s.q1/3*100) + '%';
  document.getElementById('q2').textContent = s.q2 + '/10';
  document.getElementById('q2b').style.width = (s.q2/10*100) + '%';
  document.getElementById('planDisplay').textContent = appData.isPro ? '💎 PRO' : 'FREE';
  
  let html = '';
  for (let i = 0; i < 10; i++) {
    let used = i < s.wishes && !appData.isPro;
    html += `<div class="ammo${used ? ' used' : ''}">${used ? '💨' : '🪔'}</div>`;
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
    wrapper.appendChild(img);
    wrapper.appendChild(bubble);
    div.appendChild(wrapper);
  } else {
    div.appendChild(bubble);
  }
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

// ============================================================
// ASK - REAL AI
// ============================================================
async function ask() {
  if (!appData.name || !appData.phone) {
    document.getElementById('onboard').style.display = 'flex';
    return;
  }
  
  const input = document.getElementById('q');
  const q = input.value.trim();
  if (!q) return;
  
  playSound('fire');
  appendBubble(q, true);
  input.value = '';
  
  const typingDiv = document.createElement('div');
  typingDiv.className = 'mb-3';
  typingDiv.innerHTML = '<div class="bubble-ai text-zinc-400">🔥 Thinking...</div>';
  document.getElementById('chat').appendChild(typingDiv);
  
  try {
    const res = await fetch('/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        q: q,
        name: appData.name,
        phone: appData.phone,
        uid: appData.userId
      })
    });
    
    typingDiv.remove();
    const data = await res.json();
    
    if (res.status === 402 || data.limit_reached) {
      playSound('empty');
      appendBubble(data.ans, false);
      setTimeout(openPay, 2000);
      return;
    }
    
    const s = appData.stats;
    s.wishes++;
    s.q1 = Math.min(3, s.q1 + 1);
    s.q2 = Math.min(10, s.q2 + 1);
    s.xp += data.xp_gained || 12;
    s.totalXp = (s.totalXp || 0) + (data.xp_gained || 12);
    
    if (data.level_up) {
      s.level = data.level;
      playSound('level');
      appendBubble('🔥 LEVEL UP - LVL ' + data.level + '!', false);
    }
    
    saveData();
    render();
    playSound('hit');
    appendBubble(data.ans, false);
    
  } catch(e) {
    typingDiv.remove();
    appendBubble('⚠️ Try again! - BY SPARSH SINGHAL', false);
  }
}

// ============================================================
// LEADERBOARD
// ============================================================
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
        const medal = i === 0 ? '👑' : i === 1 ? '🥈' : i === 2 ? '🥉' : `${i+1}.`;
        html += `<div class="flex justify-between items-center p-2 rounded border ${isMe ? 'bg-[#ff4d00]/20 border-[#ff4d00]/50' : 'bg-black border-zinc-800'}">
          <span class="text-sm">${medal} ${u.name} ${isMe ? '⭐' : ''}</span>
          <span class="text-[#ff4d00] font-bold">${u.xp}XP</span>
        </div>`;
      });
    }
    document.getElementById('board').innerHTML = html;
  } catch(e) {}
}

async function checkPlan() {
  if (!appData.phone) return;
  try {
    const res = await fetch('/check_plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone: appData.phone })
    });
    const data = await res.json();
    if (data.plan === 'pro') {
      appData.isPro = true;
      saveData();
      render();
    }
  } catch(e) {}
}

async function openPay() {
  if (!appData.phone || appData.phone.length !== 10) {
    document.getElementById('onboard').style.display = 'flex';
    return;
  }
  
  try {
    const res = await fetch('/create_order', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        uid: appData.userId,
        name: appData.name,
        phone: appData.phone
      })
    });
    const order = await res.json();
    
    if (order.error) {
      alert('❌ ' + order.error);
      return;
    }
    
    const options = {
      key: order.key_id,
      amount: order.amount,
      currency: order.currency,
      name: "StudyGenie Pro 🔥",
      order_id: order.order_id,
      prefill: { name: appData.name, contact: appData.phone },
      theme: { color: "#ff4d00" },
      handler: function() {
        alert('✅ PRO UNLOCKED! 🔥');
        appData.isPro = true;
        saveData();
        render();
        location.reload();
      }
    };
    new Razorpay(options).open();
  } catch(e) {
    alert('❌ Error: ' + e.message);
  }
}

// ============================================================
// CHECK ONBOARD
// ============================================================
function checkOnboard() {
  console.log('🔍 Checking onboard...');
  console.log('Name:', appData.name, 'Phone:', appData.phone);
  
  if (appData.name && appData.phone && appData.phone.length === 10) {
    document.getElementById('onboard').style.display = 'none';
    document.getElementById('app').style.display = 'block';
    initApp();
  } else {
    document.getElementById('onboard').style.display = 'flex';
    document.getElementById('app').style.display = 'none';
  }
}

// ============================================================
// INIT
// ============================================================
document.getElementById('chat').innerHTML = `
<div class="flex gap-3">
  <img src="/sparsh.jpg" class="w-12 h-12 rounded-xl border-2 border-[#ff4d00] object-cover">
  <div class="bubble-ai">
    🔥 <b>OYE WARRIOR!</b><br><br>
    Main hoon <b>Sparsh Singhal ka StudyGenie</b> — <b>KISI BHI QUESTION KA ANSWER!</b><br><br>
    ✅ Physics Numericals → Full solution<br>
    ✅ Math Problems → Step-by-step<br>
    ✅ ANY Question → Answered!<br><br>
    💪 <b>Kuch bhi pucho!</b><br><br>
    <span class="text-[#ff8a00] text-xs">BY SPARSH SINGHAL | 10 FREE AMMO</span>
  </div>
</div>
`;

checkOnboard();
console.log('🔥 StudyGenie loaded!');
console.log('📝 Fill the form and click ENTER BATTLEFIELD');
</script>
</body></html>
"""

# ===================================================================
# Vercel Handler
# ===================================================================
def handler(request, context):
    return app(request, context)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

# ===================================================================
# END - FINAL WORKING VERSION 🔥
# ===================================================================
