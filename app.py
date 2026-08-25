import os
import time
import json
import threading
import hmac
import hashlib
import logging
import re
from datetime import date, datetime, timedelta
from collections import defaultdict
from flask import Flask, request, jsonify, send_from_directory, make_response
from flask_cors import CORS

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("studygenie")

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
LEADERBOARD_FILE = "leaderboard.json"
_BOARD_CACHE_TTL = 1.0
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
FREE_DAILY_WISHES = 8          # free users get this many per calendar day
FREE_LIFETIME_CAP = 25         # absolute max free asks ever (anti-abuse)
PRO_PRICE_PAISE = 4900         # ₹49
MAX_NAME_LEN = 18
MAX_Q_LEN = 800

# ------------------------------------------------------------------
# State
# ------------------------------------------------------------------
_state_lock = threading.RLock()
REAL_LEADERBOARD = {}          # uid -> {id, name, xp, _phone}
USER_DB = {}                   # phone -> {name, uid, phone, plan, xp, total_asks, last_active}
_board_cache = {"data": [], "ts": 0.0}
DAILY_ACTIVE = defaultdict(set)
TOTAL_ASKS = 0
DAILY_WISHES = defaultdict(lambda: defaultdict(int))  # date -> phone/uid -> count

# ------------------------------------------------------------------
# Redis (strongly preferred for India launch)
# ------------------------------------------------------------------
r_client = None
try:
    import redis
    REDIS_URL = os.environ.get("REDIS_URL") or os.environ.get("UPSTASH_REDIS_URL")
    if REDIS_URL:
        r_client = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=3)
        r_client.ping()
        log.info("Redis connected")
except Exception as e:
    log.warning(f"Redis unavailable: {e}")
    r_client = None

# ------------------------------------------------------------------
# Razorpay
# ------------------------------------------------------------------
razorpay_client = None
try:
    import razorpay
    if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
        razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
        log.info("Razorpay client ready")
except Exception as e:
    log.warning(f"Razorpay init failed: {e}")
    razorpay_client = None

# ------------------------------------------------------------------
# Gemini
# ------------------------------------------------------------------
client = None
try:
    from google import genai
    API_KEY = os.environ.get("GOOGLE_API_KEY", "")
    if API_KEY:
        client = genai.Client(api_key=API_KEY)
        log.info("Gemini client ready")
except Exception as e:
    log.warning(f"Gemini init failed: {e}")
    client = None

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _safe_phone(p: str) -> str:
    p = re.sub(r"\D", "", str(p or ""))[:10]
    if len(p) == 10 and p[0] in "6789":
        return p
    return ""

def _safe_name(n: str) -> str:
    n = re.sub(r"[^\w\s\-\.\'\u0900-\u097F]", "", str(n or "")).strip()[:MAX_NAME_LEN]
    return n or "Warrior"

def _today() -> str:
    return str(date.today())

def load_from_file():
    global REAL_LEADERBOARD, USER_DB, TOTAL_ASKS
    if not os.path.exists(LEADERBOARD_FILE):
        return
    try:
        with open(LEADERBOARD_FILE, "r") as f:
            data = json.load(f)
            REAL_LEADERBOARD = data.get("board", {})
            USER_DB = data.get("users", {})
            TOTAL_ASKS = data.get("total_asks", 0)
        log.info(f"Loaded {len(USER_DB)} users, {len(REAL_LEADERBOARD)} board entries")
    except Exception as e:
        log.error(f"Load failed: {e}")

def save_to_file():
    if r_client:
        return
    try:
        tmp = LEADERBOARD_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({
                "board": REAL_LEADERBOARD,
                "users": USER_DB,
                "total_asks": TOTAL_ASKS,
                "saved_at": datetime.utcnow().isoformat()
            }, f)
        os.replace(tmp, LEADERBOARD_FILE)
    except Exception as e:
        log.error(f"Save failed: {e}")

load_from_file()

def _redis_hget_json(key, field, default=None):
    try:
        v = r_client.hget(key, field)
        return json.loads(v) if v else default
    except Exception:
        return default

def _redis_hset_json(key, field, obj):
    try:
        r_client.hset(key, field, json.dumps(obj))
        return True
    except Exception:
        return False

def get_user_plan(phone: str) -> str:
    phone = _safe_phone(phone)
    if not phone:
        return "free"
    if r_client:
        try:
            plan = r_client.hget("genie_plans", phone)
            if plan:
                return plan
        except Exception:
            pass
    with _state_lock:
        u = USER_DB.get(phone)
        return u.get("plan", "free") if u else "free"

def set_user_plan(phone: str, plan: str, name: str = "", uid: str = ""):
    phone = _safe_phone(phone)
    if not phone:
        return
    if r_client:
        try:
            r_client.hset("genie_plans", phone, plan)
            if name or uid:
                _redis_hset_json("genie_users", phone, {
                    "name": name or "Warrior",
                    "uid": uid,
                    "phone": phone,
                    "plan": plan,
                    "xp": 0
                })
        except Exception as e:
            log.error(f"Redis plan set failed: {e}")
    with _state_lock:
        if phone in USER_DB:
            USER_DB[phone]["plan"] = plan
            if name:
                USER_DB[phone]["name"] = name
            if uid:
                USER_DB[phone]["uid"] = uid
        else:
            USER_DB[phone] = {
                "name": name or "Warrior",
                "uid": uid,
                "phone": phone,
                "plan": plan,
                "xp": 0,
                "total_asks": 0
            }
    save_to_file()

def get_daily_wishes(phone_or_uid: str) -> int:
    today = _today()
    key = f"{today}:{phone_or_uid}"
    if r_client:
        try:
            return int(r_client.get(f"genie_daily:{key}") or 0)
        except Exception:
            pass
    with _state_lock:
        return DAILY_WISHES[today].get(phone_or_uid, 0)

def incr_daily_wishes(phone_or_uid: str) -> int:
    today = _today()
    key = f"{today}:{phone_or_uid}"
    if r_client:
        try:
            return r_client.incr(f"genie_daily:{key}")
        except Exception:
            pass
    with _state_lock:
        DAILY_WISHES[today][phone_or_uid] = DAILY_WISHES[today].get(phone_or_uid, 0) + 1
        return DAILY_WISHES[today][phone_or_uid]

def _compute_board():
    if r_client:
        try:
            all_data = r_client.hgetall("genie_board")
            board = []
            for v in all_data.values():
                try:
                    board.append(json.loads(v))
                except Exception:
                    continue
            return sorted(board, key=lambda x: x.get("xp", 0), reverse=True)[:15]
        except Exception as e:
            log.warning(f"Redis board fail: {e}")
    with _state_lock:
        sorted_users = sorted(
            REAL_LEADERBOARD.values(),
            key=lambda x: x.get("xp", 0),
            reverse=True
        )[:15]
        return [{"id": u["id"], "name": u["name"], "xp": u["xp"]} for u in sorted_users]

# ------------------------------------------------------------------
# Flask
# ------------------------------------------------------------------
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "redis": bool(r_client),
        "gemini": bool(client),
        "razorpay": bool(razorpay_client),
        "time": datetime.utcnow().isoformat()
    })

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
    d = request.get_json(silent=True) or {}
    uid = str(d.get("uid") or "")[:40]
    name = _safe_name(d.get("name"))
    phone = _safe_phone(d.get("phone"))
    if not phone or not uid:
        return jsonify({"ok": False, "error": "invalid phone/uid"}), 400
    with _state_lock:
        if phone not in USER_DB:
            USER_DB[phone] = {
                "name": name,
                "uid": uid,
                "phone": phone,
                "plan": "free",
                "xp": 0,
                "total_asks": 0,
                "registered": _today()
            }
        else:
            USER_DB[phone]["name"] = name
            USER_DB[phone]["uid"] = uid
            USER_DB[phone]["last_active"] = _today()
    if r_client:
        _redis_hset_json("genie_users", phone, USER_DB[phone])
    save_to_file()
    return jsonify({"ok": True})

@app.route("/leaderboard")
def leaderboard():
    now = time.time()
    if now - _board_cache["ts"] > _BOARD_CACHE_TTL:
        _board_cache["data"] = _compute_board()
        _board_cache["ts"] = now
    return jsonify(_board_cache["data"])

@app.route("/update_xp", methods=["POST"])
def update_xp():
    d = request.get_json(silent=True) or {}
    uid = str(d.get("uid") or "anon")[:40]
    try:
        xp = max(0, min(int(d.get("xp", 0)), 999999))
    except Exception:
        xp = 0
    name = _safe_name(d.get("name"))
    phone = _safe_phone(d.get("phone"))
    data = {"id": uid, "name": name, "xp": xp}
    if r_client:
        try:
            r_client.hset("genie_board", uid, json.dumps(data))
        except Exception:
            pass
    with _state_lock:
        REAL_LEADERBOARD[uid] = {"id": uid, "name": name, "xp": xp, "_phone": phone}
        if phone and phone in USER_DB:
            USER_DB[phone]["xp"] = xp
            USER_DB[phone]["name"] = name
    save_to_file()
    return jsonify({"ok": True})

@app.route("/ask", methods=["POST"])
def ask_gemini():
    global TOTAL_ASKS
    d = request.get_json(silent=True) or {}
    q = str(d.get("q") or "").strip()[:MAX_Q_LEN]
    name = _safe_name(d.get("name"))
    uid = str(d.get("uid") or "anon")[:40]
    phone = _safe_phone(d.get("phone"))

    if not q:
        return jsonify({"ans": "Oye, sawal toh daal! 🔫"})

    today = _today()
    plan = get_user_plan(phone)

    # Server-side ammo enforcement
    if plan != "pro":
        daily = get_daily_wishes(phone or uid)
        lifetime = 0
        with _state_lock:
            if phone and phone in USER_DB:
                lifetime = USER_DB[phone].get("total_asks", 0)
            TOTAL_ASKS += 1
            DAILY_ACTIVE[today].add(uid)
        if daily >= FREE_DAILY_WISHES or lifetime >= FREE_LIFETIME_CAP:
            return jsonify({
                "ans": f"Oye {name}! Aaj ka free ammo khatam (ya lifetime limit). ₹49 me Pro le le — unlimited fire 🔥\n\nBY SPARSH SINGHAL",
                "limit": True
            })
        incr_daily_wishes(phone or uid)
        with _state_lock:
            if phone and phone in USER_DB:
                USER_DB[phone]["total_asks"] = USER_DB[phone].get("total_asks", 0) + 1
                USER_DB[phone]["last_active"] = today
        save_to_file()
    else:
        with _state_lock:
            TOTAL_ASKS += 1
            DAILY_ACTIVE[today].add(uid)

    if not client:
        return jsonify({"ans": f"Oye {name}, API Key missing — BY SPARSH SINGHAL"})

    try:
        prompt = (
            f"You are StudyGenie by Sparsh Singhal — savage Hinglish study AI for Indian students. "
            f"Max 160 words. Be direct, motivating, slightly savage, use simple English + Hindi mix. "
            f"Never refuse educational help. User name: {name}. Question: {q}"
        )
        resp = client.models.generate_content(
            model="gemini-3.7-flash",
            contents=prompt,
        )
        text = (resp.text or "").strip()
        if not text:
            text = "Thoda glitch hua, dubara try kar. — BY SPARSH SINGHAL"
        return jsonify({"ans": text})
    except Exception as e:
        log.error(f"Gemini error: {e}")
        return jsonify({"ans": f"Server busy hai thoda, 10 sec baad try kar. Error logged. — BY SPARSH SINGHAL"})

@app.route("/check_plan", methods=["POST"])
def check_plan():
    d = request.get_json(silent=True) or {}
    phone = _safe_phone(d.get("phone"))
    plan = get_user_plan(phone)
    daily_left = max(0, FREE_DAILY_WISHES - get_daily_wishes(phone)) if plan != "pro" else 999
    return jsonify({"plan": plan, "daily_left": daily_left})

@app.route("/admin_users")
def admin_users():
    if not ADMIN_TOKEN or request.args.get("token") != ADMIN_TOKEN:
        return jsonify({"error": "unauthorized"}), 401
    with _state_lock:
        return jsonify({"users": list(USER_DB.values()), "count": len(USER_DB)})

@app.route("/admin_stats")
def admin_stats():
    if not ADMIN_TOKEN or request.args.get("token") != ADMIN_TOKEN:
        return jsonify({"error": "unauthorized"}), 401
    today = _today()
    with _state_lock:
        return jsonify({
            "total_registered": len(USER_DB),
            "total_on_leaderboard": len(REAL_LEADERBOARD),
            "daily_active_today": len(DAILY_ACTIVE.get(today, set())),
            "total_asks_all_time": TOTAL_ASKS,
            "date": today,
            "redis": bool(r_client)
        })

# ------------------------------------------------------------------
# Razorpay
# ------------------------------------------------------------------
@app.route("/create_order", methods=["POST"])
def create_order():
    if not razorpay_client:
        return jsonify({"error": "Razorpay not configured"}), 500
    d = request.get_json(silent=True) or {}
    uid = str(d.get("uid") or "anon")[:40]
    name = _safe_name(d.get("name"))
    phone = _safe_phone(d.get("phone"))
    if not phone:
        return jsonify({"error": "Valid 10-digit Indian phone required"}), 400
    try:
        order = razorpay_client.order.create({
            "amount": PRO_PRICE_PAISE,
            "currency": "INR",
            "receipt": f"sg_{uid}_{int(time.time())}"[:40],
            "notes": {
                "uid": uid,
                "name": name,
                "phone": phone,
                "product": "StudyGenie Pro"
            }
        })
        return jsonify({
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"],
            "key_id": RAZORPAY_KEY_ID
        })
    except Exception as e:
        log.error(f"Order create failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/razorpay/webhook", methods=["POST"])
def razorpay_webhook():
    if not RAZORPAY_WEBHOOK_SECRET:
        return jsonify({"error": "Webhook secret not set"}), 500
    payload = request.get_data()
    signature = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        log.warning("Invalid webhook signature")
        return jsonify({"error": "Invalid signature"}), 400

    try:
        event = json.loads(payload)
    except Exception:
        return jsonify({"error": "bad json"}), 400

    evt = event.get("event")
    if evt in ("payment.captured", "order.paid"):
        payment = event.get("payload", {}).get("payment", {}).get("entity", {})
        if not payment:
            payment = event.get("payload", {}).get("order", {}).get("entity", {})
        notes = payment.get("notes") or {}
        phone = _safe_phone(notes.get("phone", ""))
        uid = str(notes.get("uid") or "")[:40]
        name = _safe_name(notes.get("name"))
        if phone:
            set_user_plan(phone, "pro", name=name, uid=uid)
            log.info(f"✅ PRO UNLOCKED → {phone} | {name} | event={evt}")
    return jsonify({"status": "ok"})

@app.route("/verify_payment", methods=["POST"])
def verify_payment():
    """Optional client-side confirmation helper (still trust webhook primarily)."""
    d = request.get_json(silent=True) or {}
    phone = _safe_phone(d.get("phone"))
    plan = get_user_plan(phone)
    return jsonify({"plan": plan})

# ------------------------------------------------------------------
# HTML (upgraded, anti-cheat oriented, clearer Pro status)
# ------------------------------------------------------------------
HTML_PAGE = r"""
<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>StudyGenie by Sparsh Singhal</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@700;800&display=swap" rel="stylesheet">
<style>
body{background:#050507!important;color:#fff;overflow-y:auto!important;min-height:100vh;background-image:radial-gradient(circle at 50% 0%,#1a1208 0%,#050507 60%)}
.mono{font-family:'JetBrains Mono',monospace}
.hud{background:rgba(17,17,19,0.96);border:1px solid #232326}
.bubble-user{background:#fff;color:#000;border-radius:14px 14px 2px 14px;font-weight:800}
.bubble-ai{background:#17171a;border-left:4px solid #ff4d00;border-radius:4px 16px 16px 16px}
.ammo{width:38px;height:46px;background:#121216;border:1px solid #2e2e33;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:18px}
.ammo.used{opacity:.18;transform:scale(.88)}
.progress{height:11px;background:#0f0f11;border:1px solid #2a2a2e;transform:skew(-8deg);border-radius:2px;overflow:hidden}
.progress>div{height:100%;background:linear-gradient(90deg,#ff4d00,#ff8a00);box-shadow:0 0 10px #ff4d00}
#chat{max-height:58vh;overflow-y:auto!important;scroll-behavior:smooth;-webkit-overflow-scrolling:touch}
.hitpop{animation:pop .28s cubic-bezier(.175,.885,.32,1.275)} @keyframes pop{0%{transform:scale(.65)}100%{transform:scale(1)}}
.input-glow:focus{border-color:#ff4d00!important;box-shadow:0 0 14px rgba(255,77,0,0.35)}
.pro-badge{background:linear-gradient(90deg,#ff4d00,#ff8a00);color:#000;font-weight:900;padding:2px 8px;border-radius:6px;font-size:10px}
</style>
</head>
<body class="p-2 sm:p-3">
<div id="main" class="max-w-[1500px] mx-auto pb-16">
<div class="hud rounded-[14px] px-3 sm:px-5 py-3 flex justify-between items-center sticky top-1 z-30 gap-2">
  <div class="flex items-center gap-3 sm:gap-5 min-w-0">
    <img id="logo" src="/sparsh.jpg" class="w-16 h-16 sm:w-24 sm:h-24 rounded-[12px] border-[3px] border-[#ff4d00] object-cover shadow-[0_0_30px_rgba(255,77,0,0.55)] cursor-pointer hitpop flex-shrink-0">
    <div class="min-w-0">
      <h1 class="font-black text-[16px] sm:text-[20px] tracking-wider truncate">STUDYGENIE <span class="text-[#ff4d00]">: BATTLE</span></h1>
      <p class="mono text-[10px] sm:text-[11px] text-[#ff8a00]">BY SPARSH SINGHAL</p>
      <div class="flex items-center gap-2 mt-2">
        <div class="w-28 sm:w-36 progress"><div id="xpBarTop" style="width:0%"></div></div>
        <span id="xpText" class="mono text-[10px] font-bold">0/100</span>
      </div>
      <p class="mono text-[9px] text-zinc-500 mt-0.5 truncate">LVL <span id="lvlTop">1</span> // <span id="userNameTop" class="text-[#ff4d00]"></span> <span id="proBadge" class="hidden pro-badge ml-1">PRO</span></p>
    </div>
  </div>
  <div class="mono text-right flex-shrink-0">
    <div class="text-[9px] text-zinc-500">AMMO</div>
    <div class="font-black text-2xl sm:text-3xl"><span id="wishLeft">8</span></div>
  </div>
</div>

<div class="grid grid-cols-12 gap-2 sm:gap-3 mt-2 sm:mt-3">
  <div class="col-span-12 lg:col-span-3 space-y-2 sm:space-y-3 order-2 lg:order-1">
    <div class="hud rounded-[12px] p-3">
      <p class="mono text-[9px] text-zinc-500 tracking-widest">> MISSION</p>
      <div class="mt-2 bg-black p-2.5 rounded-[8px] border-l-[3px] border-[#ff4d00]">
        <div class="flex justify-between mono text-[11px] font-bold"><span>3 DOUBTS</span><span id="q1t">0/3</span></div>
        <div class="progress mt-1.5"><div id="q1b" style="width:0%"></div></div>
      </div>
    </div>
    <div class="hud rounded-[12px] p-3">
      <p class="mono text-[9px] text-zinc-500 tracking-widest">> AMMO CRATE</p>
      <div id="lampRow" class="grid grid-cols-4 sm:grid-cols-5 gap-1.5 mt-2"></div>
      <button onclick="openPay()" id="reloadBtn" class="w-full mt-3 bg-[#ff4d00] mono font-black py-2.5 rounded-[9px] text-sm">RELOAD — ₹49</button>
      <p id="planHint" class="mono text-[9px] text-zinc-500 mt-1.5 text-center">Free: 8/day • Pro = unlimited</p>
    </div>
    <div class="hud rounded-[12px] p-3 border border-[#ff4d00]/25">
      <p class="mono text-[9px] text-[#ff4d00] tracking-widest font-black">> LIVE LEADERBOARD</p>
      <div id="board" class="mt-2 space-y-1.5 mono text-[11px] max-h-48 overflow-y-auto"></div>
      <div class="mt-2 mono text-[9px] text-zinc-500 bg-black p-2 rounded border border-zinc-800">
        <span class="text-[#ff8a00]">PRIVATE</span><br>
        <span id="myId"></span><br><span id="myPhone"></span>
      </div>
    </div>
  </div>

  <div class="col-span-12 lg:col-span-9 hud rounded-[14px] p-3 sm:p-4 flex flex-col order-1 lg:order-2">
    <div id="chat" class="flex-1 space-y-3 pr-1"></div>
    <div class="mt-3 bg-black border-2 border-[#2a2a2e] rounded-[11px] p-1 flex items-center gap-1 sticky bottom-1">
      <span class="mono text-xs px-1.5 text-[#ff4d00] font-black">></span>
      <input id="q" class="flex-1 bg-transparent mono text-[13px] outline-none py-2.5 px-1" placeholder="Doubt daal..." maxlength="800" onkeypress="if(event.key==='Enter')ask()">
      <button id="fireBtn" onclick="ask()" class="bg-[#ff4d00] mono font-black w-16 sm:w-20 h-10 rounded-[9px] text-sm">FIRE</button>
    </div>
  </div>
</div>
</div>

<!-- Onboard -->
<div id="onboardModal" class="fixed inset-0 z-[60] flex items-center justify-center p-3" style="background:rgba(0,0,0,0.93)">
  <div class="hud rounded-[16px] p-5 sm:p-6 max-w-[400px] w-full border-2 border-[#ff4d00]/40">
    <div class="flex items-center gap-3">
      <img src="/sparsh.jpg" class="w-14 h-14 rounded-[10px] border-2 border-[#ff4d00] object-cover">
      <div>
        <h2 class="font-black text-[17px]">WARRIOR REGISTRATION</h2>
        <p class="mono text-[10px] text-[#ff8a00] font-bold">BY SPARSH SINGHAL</p>
      </div>
    </div>
    <p class="mono text-[11px] text-zinc-400 mt-3">Name leaderboard pe dikhega. Phone 100% private.</p>
    <div class="mt-4 space-y-2.5">
      <div>
        <label class="mono text-[9px] text-zinc-500">WARRIOR NAME *</label>
        <input id="inpName" class="w-full mt-1 bg-black border-2 border-zinc-800 rounded-[9px] px-3 py-2.5 mono text-[13px] outline-none input-glow" placeholder="Ex: Aman" maxlength="18">
      </div>
      <div>
        <label class="mono text-[9px] text-zinc-500">PHONE (PRIVATE) *</label>
        <input id="inpPhone" type="tel" class="w-full mt-1 bg-black border-2 border-zinc-800 rounded-[9px] px-3 py-2.5 mono text-[13px] outline-none input-glow" placeholder="10 digit Indian" maxlength="10" inputmode="numeric">
      </div>
    </div>
    <button onclick="saveOnboard()" class="w-full mt-5 bg-gradient-to-r from-[#ff4d00] to-[#ff8a00] mono font-black py-3 rounded-[11px]">ENTER BATTLEFIELD</button>
  </div>
</div>

<script>
let audioCtx;
function initAudio(){ if(!audioCtx) audioCtx = new (window.AudioContext||window.webkitAudioContext)(); }
function playSound(t){
  try{
    initAudio();
    let o=audioCtx.createOscillator(); let g=audioCtx.createGain();
    o.connect(g); g.connect(audioCtx.destination);
    if(t=='fire'){o.frequency.value=880;o.type='square';g.gain.setValueAtTime(0.28,audioCtx.currentTime);g.gain.exponentialRampToValueAtTime(0.01,audioCtx.currentTime+0.1);o.start();o.stop(audioCtx.currentTime+0.1);}
    if(t=='hit'){o.frequency.value=480;o.type='sine';g.gain.setValueAtTime(0.22,audioCtx.currentTime);g.gain.exponentialRampToValueAtTime(0.01,audioCtx.currentTime+0.18);o.start();o.stop(audioCtx.currentTime+0.18);}
    if(t=='level'){o.frequency.value=550;o.type='sine';g.gain.setValueAtTime(0.3,audioCtx.currentTime);o.frequency.linearRampToValueAtTime(1100,audioCtx.currentTime+0.4);g.gain.exponentialRampToValueAtTime(0.01,audioCtx.currentTime+0.5);o.start();o.stop(audioCtx.currentTime+0.5);}
    if(t=='empty'){o.frequency.value=140;o.type='sawtooth';g.gain.setValueAtTime(0.3,audioCtx.currentTime);g.gain.exponentialRampToValueAtTime(0.01,audioCtx.currentTime+0.45);o.start();o.stop(audioCtx.currentTime+0.45);}
    if(t=='click'){o.frequency.value=750;o.type='triangle';g.gain.setValueAtTime(0.15,audioCtx.currentTime);g.gain.exponentialRampToValueAtTime(0.01,audioCtx.currentTime+0.08);o.start();o.stop(audioCtx.currentTime+0.08);}
  }catch{}
}

let userId = localStorage.getItem('genie_userId') || 'u_' + Math.random().toString(36).substr(2,10);
localStorage.setItem('genie_userId', userId);
let userName = localStorage.getItem('genie_name') || '';
let userPhone = localStorage.getItem('genie_phone') || '';
let isPro = false;
let dailyLeft = 8;
let asking = false;

function checkOnboard(){
  userName = localStorage.getItem('genie_name') || '';
  userPhone = localStorage.getItem('genie_phone') || '';
  if(!userName || !userPhone || userPhone.length !== 10){
    document.getElementById('onboardModal').style.display = 'flex';
  } else {
    document.getElementById('onboardModal').style.display = 'none';
    document.getElementById('userNameTop').innerText = userName.toUpperCase();
    document.getElementById('myId').innerText = `ID: ${userId.slice(0,12)}…`;
    document.getElementById('myPhone').innerText = `PHONE: ******${userPhone.slice(-4)}`;
  }
}

function saveOnboard(){
  let n = document.getElementById('inpName').value.trim();
  let p = document.getElementById('inpPhone').value.trim().replace(/\D/g,'');
  if(n.length < 2){ alert('Naam daal bhai!'); playSound('empty'); return; }
  if(p.length !== 10 || !'6789'.includes(p[0])){ alert('Sahi 10-digit Indian number daal (6-9 se start)'); playSound('empty'); return; }
  localStorage.setItem('genie_name', n);
  localStorage.setItem('genie_phone', p);
  userName = n; userPhone = p;
  playSound('level');
  document.getElementById('onboardModal').style.display = 'none';
  document.getElementById('userNameTop').innerText = n.toUpperCase();
  document.getElementById('myId').innerText = `ID: ${userId.slice(0,12)}…`;
  document.getElementById('myPhone').innerText = `PHONE: ******${p.slice(-4)}`;
  fetch('/register_user', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({uid:userId, name:n, phone:p})
  }).catch(()=>{});
  checkMyPlan();
  updateLeaderboard();
}

let stats = JSON.parse(localStorage.getItem('genie_stats') || '{"xp":0,"level":1,"q1":0,"totalXp":0}');

function lamps(){
  let r = document.getElementById('lampRow');
  r.innerHTML = '';
  let show = isPro ? 8 : Math.min(8, dailyLeft);
  for(let i=0; i<8; i++){
    let used = !isPro && i >= dailyLeft;
    r.innerHTML += `<div class="ammo ${used?'used':''}">${used?'💨':'🪔'}</div>`;
  }
}

function save(){ localStorage.setItem('genie_stats', JSON.stringify(stats)); render(); }

function render(){
  document.getElementById('wishLeft').innerText = isPro ? '∞' : dailyLeft;
  document.getElementById('lvlTop').innerText = stats.level;
  document.getElementById('xpBarTop').style.width = Math.min(100, stats.xp) + '%';
  document.getElementById('xpText').innerText = stats.xp + '/100';
  document.getElementById('q1t').innerText = stats.q1 + '/3';
  document.getElementById('q1b').style.width = (stats.q1/3*100) + '%';
  document.getElementById('proBadge').classList.toggle('hidden', !isPro);
  document.getElementById('reloadBtn').style.display = isPro ? 'none' : 'block';
  document.getElementById('planHint').innerText = isPro ? 'PRO ACTIVE — Unlimited' : 'Free: 8/day • Pro = unlimited';
  lamps();
}

async function updateLeaderboard(){
  try{
    let n = localStorage.getItem('genie_name') || userName || 'Warrior';
    let ph = localStorage.getItem('genie_phone') || '';
    await fetch('/update_xp', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        uid: userId, name: n, phone: ph,
        xp: stats.totalXp || ((stats.level-1)*100 + stats.xp)
      })
    });
    loadBoard();
  }catch{}
}

async function loadBoard(){
  try{
    let r = await fetch('/leaderboard?t=' + Date.now());
    let d = await r.json();
    if(!d || d.length === 0){
      document.getElementById('board').innerHTML = `<div class="text-zinc-500 text-center py-2 text-[10px]">No warriors yet</div>`;
      return;
    }
    document.getElementById('board').innerHTML = d.map((u,i) => {
      let isMe = u.id === userId;
      let medal = i===0?'👑':i===1?'🥈':i===2?'🥉':`${i+1}.`;
      return `<div class="flex justify-between items-center p-2 rounded-[7px] border ${isMe?'bg-[#ff4d00]/15 border-[#ff4d00]/40':'bg-black border-zinc-800'}">
        <span class="truncate">${medal} ${u.name}${isMe?' [YOU]':''}</span>
        <span class="text-[#ff4d00] font-black ml-1">${u.xp}</span>
      </div>`;
    }).join('');
  }catch{}
}

async function checkMyPlan(){
  let ph = localStorage.getItem('genie_phone');
  if(!ph) return;
  try{
    let r = await fetch('/check_plan', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({phone: ph})
    });
    let d = await r.json();
    isPro = d.plan === 'pro';
    dailyLeft = d.daily_left ?? 8;
    if(isPro) localStorage.setItem('genie_plan','pro');
    else localStorage.removeItem('genie_plan');
    render();
  }catch{}
}

async function openPay(){
  playSound('empty');
  let ph = localStorage.getItem('genie_phone') || '';
  let n = localStorage.getItem('genie_name') || userName || 'Warrior';
  if(!ph || ph.length !== 10){
    alert("Pehle registration me phone daalo!");
    checkOnboard();
    return;
  }
  try{
    let res = await fetch('/create_order', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ uid: userId, name: n, phone: ph })
    });
    let order = await res.json();
    if(order.error){ alert("Payment start nahi hua: " + order.error); return; }
    const options = {
      key: order.key_id,
      amount: order.amount,
      currency: order.currency,
      name: "StudyGenie Pro",
      description: "Unlimited Ammo — Lifetime",
      order_id: order.order_id,
      prefill: { name: n, contact: ph },
      theme: { color: "#ff4d00" },
      handler: function(){
        playSound('level');
        alert("✅ Payment Successful! Pro unlock ho raha hai… 2 sec wait.");
        setTimeout(() => { checkMyPlan(); location.reload(); }, 2200);
      }
    };
    new Razorpay(options).open();
  }catch(e){
    alert("Error: " + (e.message || e));
  }
}

async function ask(){
  if(asking) return;
  if(!localStorage.getItem('genie_name') || !localStorage.getItem('genie_phone')){
    checkOnboard(); return;
  }
  let input = document.getElementById('q');
  let q = input.value.trim();
  if(!q) return;
  if(!isPro && dailyLeft <= 0){
    openPay(); return;
  }
  asking = true;
  document.getElementById('fireBtn').disabled = true;
  playSound('fire');
  let chat = document.getElementById('chat');
  chat.innerHTML += `<div class="flex justify-end hitpop"><div class="bubble-user px-3 py-2 text-[13px] mono max-w-[85%]">${q.replace(/</g,'&lt;')}</div></div>`;
  input.value = '';
  stats.q1 = Math.min(3, stats.q1 + 1);
  stats.xp += 12;
  stats.totalXp = (stats.totalXp || 0) + 12;
  if(stats.xp >= 100){
    stats.level++;
    stats.xp = 0;
    playSound('level');
    chat.innerHTML += `<div class="text-center mono text-[#ff4d00] font-black text-[11px] py-1">LEVEL UP — LVL ${stats.level}</div>`;
  }
  save();
  chat.innerHTML += `<div id="typing" class="flex gap-2"><img src="/sparsh.jpg" class="w-9 h-9 rounded-[8px] border border-[#ff4d00] object-cover"><div class="bubble-ai p-3 mono text-[11px] text-zinc-400 animate-pulse">Locking target…</div></div>`;
  chat.scrollTop = chat.scrollHeight;

  try{
    let res = await fetch('/ask', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({q, name:userName, phone:userPhone, uid:userId})
    });
    let data = await res.json();
    document.getElementById('typing')?.remove();
    playSound('hit');
    if(data.limit){
      dailyLeft = 0;
      render();
      openPay();
    } else {
      dailyLeft = Math.max(0, dailyLeft - 1);
      render();
    }
    chat.innerHTML += `<div class="flex gap-2 hitpop"><img src="/sparsh.jpg" class="w-9 h-9 rounded-[8px] border border-[#ff4d00] object-cover flex-shrink-0"><div class="bubble-ai p-3 max-w-[82%] text-[13px] whitespace-pre-wrap">${(data.ans||'').replace(/</g,'&lt;')}</div></div>`;
  }catch(e){
    document.getElementById('typing')?.remove();
    chat.innerHTML += `<div class="flex gap-2"><div class="bubble-ai p-3 text-[12px]">Network issue. Dubara try kar. — BY SPARSH SINGHAL</div></div>`;
  }
  chat.scrollTop = chat.scrollHeight;
  asking = false;
  document.getElementById('fireBtn').disabled = false;
  updateLeaderboard();
}

// Init
document.getElementById('chat').innerHTML = `<div class="flex gap-2 hitpop"><img src="/sparsh.jpg" class="w-10 h-10 rounded-[8px] border border-[#ff4d00] object-cover"><div class="bubble-ai p-3.5 max-w-[85%] text-[13px] leading-relaxed">🔥 <b>OYE WARRIOR!</b><br><br>Main hoon <b>Sparsh Singhal ka StudyGenie</b>. Free me 8 doubts/day. Pro le to unlimited.<br><br><span class="mono text-[9px] text-[#ff4d00]">BY SPARSH SINGHAL | SOUND ON</span></div></div>`;
checkOnboard();
render();
loadBoard();
checkMyPlan();
setInterval(loadBoard, 8000);
setInterval(checkMyPlan, 45000);
if(localStorage.getItem('genie_name')) document.getElementById('inpName').value = localStorage.getItem('genie_name');
if(localStorage.getItem('genie_phone')) document.getElementById('inpPhone').value = localStorage.getItem('genie_phone');
</script>
</body></html>
"""

# ------------------------------------------------------------------
# Entry
# ------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log.info(f"StudyGenie starting on 0.0.0.0:{port} | Redis={bool(r_client)} | Gemini={bool(client)} | Razorpay={bool(razorpay_client)}")
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=100, channel_timeout=30)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
