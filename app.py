# ===================================================================
# STUDYGENIE - FINALLY WORKING 🔥
# By Sparsh Singhal - GROQ API WORKING!
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
import urllib.request
import urllib.error

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

# ===================================================================
# Config - YOUR API KEY IS HERE 🔥
# ===================================================================
SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_urlsafe(32))
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", secrets.token_urlsafe(32))

# 🔥🔥🔥 YOUR GROQ API KEY - HARDCODED 🔥🔥🔥
GROQ_API_KEY = "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"

FREE_ASK_LIMIT = int(os.environ.get("FREE_ASK_LIMIT", "10"))
PRO_AMOUNT = int(os.environ.get("PRO_AMOUNT", "4900"))
DEV_PASSWORD = os.environ.get("DEV_PASSWORD", "sparsh123")

# ===================================================================
# Redis (Optional)
# ===================================================================
try:
    import redis
    REDIS_AVAILABLE = True
except:
    REDIS_AVAILABLE = False
    redis = None

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
    
    def get_user(self, phone):
        if not phone:
            return None
        return self.users.get(phone)
    
    def get_user_by_uid(self, uid):
        for user in self.users.values():
            if user.get("uid") == uid:
                return user
        return None
    
    def save_user(self, data):
        try:
            phone = data.get("phone")
            if not phone:
                return False
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
        return self.save_user(user)
    
    def get_leaderboard(self, limit=10):
        sorted_users = sorted(self.leaderboard.values(), key=lambda x: x.get("xp", 0), reverse=True)[:limit]
        return [{"id": u.get("id"), "name": u.get("name", "Warrior"), "xp": u.get("xp", 0), "level": u.get("level", 1), "rank": i+1} for i, u in enumerate(sorted_users)]
    
    def update_leaderboard(self, uid, name, xp, phone=None, level=1):
        self.leaderboard[uid] = {"id": uid, "name": name, "xp": xp, "level": level}
    
    def increment_ask(self, uid):
        self.ask_counts[uid] = self.ask_counts.get(uid, 0) + 1
        self.total_asks += 1
        return self.ask_counts[uid]
    
    def get_ask_count(self, uid):
        return self.ask_counts.get(uid, 0)
    
    def get_stats(self):
        return {"total_users": len(self.users), "total_asks": self.total_asks, "date": datetime.utcnow().strftime("%Y-%m-%d")}

storage = Storage()

# ===================================================================
# AI SERVICE - DIRECT API CALL 🔥
# ===================================================================
class AIService:
    def __init__(self):
        self.api_key = GROQ_API_KEY
        self.is_working = bool(self.api_key and self.api_key != "gsk_xxxxx")
        log.info(f"🔥 AI Service: {'WORKING' if self.is_working else 'NOT CONFIGURED'}")
    
    def generate(self, question, name="Warrior", is_pro=False):
        """Direct API call to GROQ - 100% Working!"""
        
        if not self.is_working:
            return f"🔥 Oye {name}! API key set nahi hai! Please check GROQ_API_KEY."
        
        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            
            data = {
                "model": "mixtral-8x7b-32768",
                "messages": [
                    {
                        "role": "system",
                        "content": f"You are StudyGenie, an AI tutor created by Sparsh Singhal. User: {name}. Answer in Hinglish. Be accurate, helpful, and savage in a fun way. Show steps for numerical problems."
                    },
                    {
                        "role": "user",
                        "content": question
                    }
                ],
                "temperature": 0.7,
                "max_tokens": 600
            }
            
            json_data = json.dumps(data).encode('utf-8')
            
            req = urllib.request.Request(
                url,
                data=json_data,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                }
            )
            
            with urllib.request.urlopen(req, timeout=20) as response:
                response_data = response.read().decode('utf-8')
                result = json.loads(response_data)
                
                if "choices" in result and len(result["choices"]) > 0:
                    text = result["choices"][0]["message"]["content"]
                    if text:
                        log.info(f"✅ AI Response generated successfully")
                        return text.strip()
                
                return f"⚠️ No response from AI. Please try again.\n\n- BY SPARSH SINGHAL"
                
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else ""
            log.error(f"HTTP Error: {e.code} - {error_body}")
            return f"⚠️ API Error: {e.code}\n\n{error_body[:200]}\n\n- BY SPARSH SINGHAL"
        except urllib.error.URLError as e:
            log.error(f"URL Error: {e.reason}")
            return f"⚠️ Network Error: {e.reason}\n\nPlease try again.\n\n- BY SPARSH SINGHAL"
        except Exception as e:
            log.error(f"General Error: {str(e)}")
            return f"⚠️ Error: {str(e)}\n\nPlease try again.\n\n- BY SPARSH SINGHAL"

ai_service = AIService()

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
            return jsonify({"ok": True, "uid": existing.get("uid"), "name": existing.get("name"), "phone": existing.get("phone"), "plan": existing.get("plan", "free")})
        
        user_data = {"phone": phone, "uid": uid, "name": name, "plan": "free", "xp": 0, "level": 1}
        
        if storage.save_user(user_data):
            storage.update_leaderboard(uid, name, 0, phone, 1)
            return jsonify({"ok": True, "uid": uid, "name": name, "phone": phone, "plan": "free"})
        
        return jsonify({"error": "Failed to save user"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/leaderboard")
def get_leaderboard():
    try:
        return jsonify(storage.get_leaderboard(10))
    except:
        return jsonify([]), 200

@app.route("/update_xp", methods=["POST"])
def update_xp():
    try:
        data = request.get_json(silent=True) or {}
        uid = str(data.get("uid", ""))[:64]
        xp = int(data.get("xp", 0))
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
        data = request.get_json(silent=True) or {}
        question = (data.get("q") or "").strip()
        name = clean_name(data.get("name", "Warrior"))
        uid = str(data.get("uid", "anon"))[:64]
        phone = clean_phone(data.get("phone"))
        
        if len(question) > 2000:
            question = question[:2000]
        if not question:
            return jsonify({"error": "Empty question"}), 400
        
        plan = storage.get_plan(phone) if phone else "free"
        used = storage.get_ask_count(uid)
        
        if plan == "free" and used >= FREE_ASK_LIMIT:
            return jsonify({"limit_reached": True, "ans": f"🚀 AMMO KHATAM! 🔫\n\nOye {name}! Your free ammo is over!\n\n💎 RELOAD NOW - ₹49 Only!\n\n- BY SPARSH SINGHAL"}), 402
        
        # 🔥 GENERATE ANSWER
        response_text = ai_service.generate(question, name, plan == "pro")
        
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
            storage.update_leaderboard(uid, user.get("name", name), user.get("xp", 0), phone, user.get("level", 1))
        
        return jsonify({"ans": response_text, "xp_gained": xp_gained, "level_up": level_up, "level": user.get("level", 1) if user else 1})
        
    except Exception as e:
        log.error(f"Ask error: {e}")
        return jsonify({"ans": f"⚠️ Error: {str(e)}"}), 500

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
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/admin/users")
@admin_required
def admin_users():
    try:
        users = list(storage.users.values())[:100]
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

# ===================================================================
# HTML
# ===================================================================
HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>StudyGenie 🔥</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: #050507; color: #fff; font-family: system-ui, sans-serif; min-height: 100vh; background-image: radial-gradient(circle at 50% 0%, #1a1208 0%, #050507 60%); }
.hud { background: rgba(17,17,19,0.95); border: 1px solid #232326; border-radius: 16px; padding: 20px; backdrop-filter: blur(10px); }
.btn-fire { background: linear-gradient(90deg, #ff4d00, #ff8a00); border: none; padding: 12px 28px; border-radius: 12px; font-weight: 900; cursor: pointer; color: #fff; font-size: 16px; transition: all 0.3s; }
.btn-fire:hover { transform: scale(1.05); }
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
.dev-badge { background: #ff4d00; color: #fff; font-size: 10px; padding: 2px 8px; border-radius: 10px; display: none; font-weight: 900; }
</style>
</head>
<body>

<div id="onboard" style="position:fixed;inset:0;background:rgba(0,0,0,0.97);display:flex;align-items:center;justify-content:center;z-index:999;backdrop-filter:blur(10px)">
  <div class="hud max-w-[420px] w-full">
    <div class="flex items-center gap-4">
      <img src="/sparsh.jpg" class="w-16 h-16 rounded-xl border-2 border-[#ff4d00] object-cover">
      <div>
        <h2 class="text-2xl font-black">🔥 REGISTER</h2>
        <p class="text-[#ff8a00] text-sm font-bold">BY SPARSH SINGHAL</p>
      </div>
    </div>
    <p class="text-sm text-zinc-400 mt-3">Enter the battlefield!</p>
    <div class="mt-4 space-y-3">
      <input id="inpName" class="w-full bg-black border-2 border-zinc-800 rounded-xl px-4 py-3 text-white outline-none input-glow" placeholder="⚡ Your Name" maxlength="20">
      <input id="inpPhone" class="w-full bg-black border-2 border-zinc-800 rounded-xl px-4 py-3 text-white outline-none input-glow" placeholder="📱 10 digit phone" maxlength="10" type="tel">
    </div>
    <button onclick="registerUser()" class="btn-fire w-full mt-4" id="registerBtn">🔥 ENTER</button>
    <p id="registerStatus" class="text-xs text-zinc-500 mt-2 text-center"></p>
  </div>
</div>

<div id="app" style="display:none;max-width:1500px;margin:0 auto;padding:16px">
  <div class="hud flex justify-between items-center sticky top-2 z-30">
    <div class="flex items-center gap-6">
      <img id="logo" src="/sparsh.jpg" class="w-24 h-24 rounded-[16px] border-4 border-[#ff4d00] object-cover cursor-pointer" onclick="handleLogoClick()">
      <div>
        <h1 class="text-2xl font-black">STUDYGENIE 🔥</h1>
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
      <div id="devBadge" class="dev-badge">🔓 DEV</div>
      <div class="text-right">
        <div class="text-xs text-zinc-500">🔥 AMMO</div>
        <div class="text-3xl font-black"><span id="ammoLeft">10</span>/10</div>
      </div>
      <div class="w-px h-12 bg-zinc-800"></div>
      <div class="text-right">
        <div class="text-xs text-zinc-500">💎 PLAN</div>
        <div id="planDisplay" class="font-bold text-[#ff8a00]">FREE</div>
      </div>
    </div>
  </div>

  <div class="grid grid-cols-12 gap-4 mt-4">
    <div class="col-span-12 lg:col-span-3 space-y-4">
      <div class="hud">
        <p class="text-xs text-zinc-500">🎯 MISSIONS</p>
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
        <p class="text-xs text-zinc-500">🔫 AMMO CRATE</p>
        <div id="lamps" class="mt-2"></div>
        <button onclick="openPay()" class="btn-fire w-full mt-3 text-sm">💎 RELOAD - ₹49</button>
      </div>

      <div class="hud">
        <p class="text-xs text-[#ff4d00] font-black">🏆 LEADERBOARD</p>
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
          <input id="q" class="flex-1 bg-black border-2 border-zinc-800 rounded-xl px-4 py-3 text-white outline-none input-glow" placeholder="🔥 ANY QUESTION..." onkeypress="if(event.key==='Enter')ask()">
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
const STORAGE_KEY = 'studygenie_data';
let appData = {
  userId: 'user_' + Math.random().toString(36).substr(2,9),
  name: '',
  phone: '',
  isPro: false,
  isDev: false,
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
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(appData));
  } catch(e) {}
}

loadData();

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

let logoClickCount = 0;
let logoClickTimer = null;

function handleLogoClick() {
  playSound('click');
  logoClickCount++;
  clearTimeout(logoClickTimer);
  logoClickTimer = setTimeout(() => { logoClickCount = 0; }, 3000);
  
  if (logoClickCount >= 5) {
    const password = prompt('🔐 Enter Secret Code:');
    if (password === 'sparsh123') {
      appData.isDev = !appData.isDev;
      saveData();
      if (appData.isDev) {
        document.getElementById('devBadge').style.display = 'inline-block';
        alert('🔓 DEV MODE ACTIVATED!');
      } else {
        document.getElementById('devBadge').style.display = 'none';
        alert('🔒 DEV MODE DEACTIVATED');
      }
      render();
    }
    logoClickCount = 0;
  }
}

function registerUser() {
  const name = document.getElementById('inpName').value.trim();
  const phone = document.getElementById('inpPhone').value.trim().replace(/[^0-9]/g, '');
  
  if (!name || name.length < 2) { alert('Enter name!'); return; }
  if (!phone || phone.length !== 10) { alert('Enter 10 digit phone!'); return; }
  
  appData.name = name;
  appData.phone = phone;
  saveData();
  
  fetch('/register_user', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ uid: appData.userId, name, phone })
  })
  .then(res => res.json())
  .then(data => {
    if (data.ok) {
      document.getElementById('onboard').style.display = 'none';
      document.getElementById('app').style.display = 'block';
      initApp();
    }
  });
}

function initApp() {
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
  const unlimited = appData.isPro || appData.isDev;
  document.getElementById('ammoLeft').textContent = unlimited ? '∞' : (10 - s.wishes);
  document.getElementById('lvl').textContent = s.level;
  document.getElementById('xpBar').style.width = Math.min(100, s.xp) + '%';
  document.getElementById('xpText').textContent = s.xp + '/100';
  document.getElementById('q1').textContent = s.q1 + '/3';
  document.getElementById('q1b').style.width = (s.q1/3*100) + '%';
  document.getElementById('q2').textContent = s.q2 + '/10';
  document.getElementById('q2b').style.width = (s.q2/10*100) + '%';
  
  let html = '';
  for (let i = 0; i < 10; i++) {
    let used = i < s.wishes && !appData.isPro && !appData.isDev;
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
      body: JSON.stringify({ q, name: appData.name, phone: appData.phone, uid: appData.userId })
    });
    
    typingDiv.remove();
    const data = await res.json();
    
    if (res.status === 402 || data.limit_reached) {
      playSound('empty');
      appendBubble(data.ans, false);
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

async function loadBoard() {
  try {
    const res = await fetch('/leaderboard');
    const data = await res.json();
    let html = '';
    data.forEach((u, i) => {
      const isMe = u.id === appData.userId;
      const medal = i === 0 ? '👑' : i === 1 ? '🥈' : i === 2 ? '🥉' : `${i+1}.`;
      html += `<div class="flex justify-between items-center p-2 rounded border ${isMe ? 'bg-[#ff4d00]/20' : 'bg-black'}">
        <span>${medal} ${u.name} ${isMe ? '⭐' : ''}</span>
        <span class="text-[#ff4d00] font-bold">${u.xp}XP</span>
      </div>`;
    });
    document.getElementById('board').innerHTML = html || '<div class="text-zinc-500">No warriors yet</div>';
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
  alert('💎 Payment coming soon!');
}

function checkOnboard() {
  if (appData.name && appData.phone && appData.phone.length === 10) {
    document.getElementById('onboard').style.display = 'none';
    document.getElementById('app').style.display = 'block';
    initApp();
  }
}

document.getElementById('chat').innerHTML = `
<div class="flex gap-3">
  <img src="/sparsh.jpg" class="w-12 h-12 rounded-xl border-2 border-[#ff4d00] object-cover">
  <div class="bubble-ai">
    🔥 <b>OYE WARRIOR!</b><br><br>
    Main hoon <b>Sparsh Singhal ka StudyGenie</b><br><br>
    ✅ ANY Question → Answered!<br><br>
    💪 <b>Kuch bhi pucho!</b><br><br>
    <span class="text-[#ff8a00] text-xs">BY SPARSH SINGHAL | 10 FREE AMMO</span>
  </div>
</div>
`;

checkOnboard();
console.log('🔥 StudyGenie loaded!');
</script>
</body></html>
"""

# ===================================================================
# Vercel Handler
# ===================================================================
def handler(request, context):
    return app(request, context)

# ===================================================================
# Run
# ===================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n🔥 StudyGenie starting on http://localhost:{port}")
    print(f"🤖 AI: {'WORKING' if ai_service.is_working else 'FAILED'}")
    print(f"🔐 Dev Mode: Click logo 5x → password 'sparsh123'\n")
    app.run(host="0.0.0.0", port=port, debug=False)

# ===================================================================
# END 🔥
# ===================================================================
