from flask import Flask, request, jsonify
import os, random
from datetime import datetime

app = Flask(__name__)

# Memory - safe
USERS = {}
LEADERBOARD = {}

def get_user(ip):
    today = str(datetime.now().date())
    if ip not in USERS:
        USERS[ip] = {"xp": 0, "streak": 1, "last_day": today, "topics": []}
    u = USERS[ip]
    if u["last_day"]!= today:
        u["streak"] += 1
        u["last_day"] = today
    return u

def get_ai(topic, mins):
    api_key = os.getenv("GEMINI_KEY")
    if not api_key:
        return "GEMINI_KEY set nahi hai. Vercel > Settings > Env Variables me add kar."

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        prompt = f"Explain {topic} in Hinglish for {mins} minutes. 5 points, 1 example, 1 trick."
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )
        return response.text
    except Exception as e:
        return f"AI Error: {str(e)[:600]}"

@app.route("/")
def home():
    u = get_user(request.remote_addr)
    # HTML inside Python so no template file needed = never fails
    return f"""
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>StudyGenie - Sparsh Singhal</title>
<style>
body{{background:#000;color:#fff;font-family:system-ui;text-align:center;padding:20px;margin:0}}
input{{width:90%;max-width:500px;padding:15px;border-radius:12px;border:none;font-size:16px}}
button{{padding:12px 20px;margin:6px;border-radius:25px;border:none;font-weight:bold;cursor:pointer}}
.sec{{background:#222;color:#fff;border:1px solid #333}}
.card{{background:#111;padding:18px;border-radius:16px;max-width:650px;margin:20px auto;text-align:left;white-space:pre-wrap;border:1px solid #222;line-height:1.6}}
.pill{{background:#1a1a1a;padding:8px 14px;border-radius:20px;font-size:14px;border:1px solid #222;display:inline-block;margin:4px}}
.brand{{background:#111;padding:25px;border-radius:20px;max-width:650px;margin:40px auto;border:1px solid #333}}
</style>
</head>
<body>
<h1>StudyGenie 🔥</h1>
<p style="color:#888">By Sparsh Singhal</p>
<div>
<span class="pill">🔥 Streak: {u["streak"]} din</span>
<span class="pill">⭐ XP: {u["xp"]}</span>
</div>
<br>
<input id="t" placeholder="Topic likho e.g. OOPS">
<br><br>
<button onclick="ask('1')">⚡ 1 Min</button>
<button onclick="ask('5')">🧠 5 Min</button>
<button onclick="ask('10')">👑 10 Min</button>
<br>
<button class="sec" onclick="api('/api/daily')">📅 /daily</button>
<button class="sec" onclick="api('/api/leaderboard')">🏆 /leaderboard</button>
<div id="ans" class="card">Ready hai bhai - topic likh ke dabaa, pakka chalega!</div>
<div class="brand">
<h2>Sparsh Singhal</h2>
<p style="color:#aaa">Founder - StudyGenie</p>
<p style="color:#666;font-size:12px">V5.0 - Live & Stable</p>
</div>
<script>
function ask(m){{
 let topic=document.getElementById('t').value;
 if(!topic){{alert('Topic likh');return}}
 document.getElementById('ans').innerText='Soch raha hu...';
 fetch('/api/ask',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{topic:topic,min:m}})}})
.then(r=>r.json()).then(d=>{{document.getElementById('ans').innerText=d.reply}})
}}
function api(u){{document.getElementById('ans').innerText='Loading...';fetch(u).then(r=>r.json()).then(d=>{{document.getElementById('ans').innerText=d.reply}})}}
</script>
</body>
</html>
"""

@app.route("/api/ask", methods=["POST"])
def ask_api():
    data = request.get_json() or {}
    ip = request.remote_addr
    u = get_user(ip)
    mins = data.get("min", "5")
    u["xp"] += 10 * int(mins)
    LEADERBOARD[ip] = u["xp"]
    u["topics"].append(data.get("topic",""))
    reply = get_ai(data.get("topic",""), mins)
    return jsonify({"reply": reply, "streak": u["streak"], "xp": u["xp"]})

@app.route("/api/daily")
def daily():
    return jsonify({"reply": f"📅 Aaj ka mission: {random.choice(['Arrays','OOPS','DBMS','SQL'])} - 50 XP"})

@app.route("/api/leaderboard")
def lb():
    if not LEADERBOARD:
        return jsonify({"reply": "Leaderboard khali hai - tu pehla ban!"})
    top = sorted(LEADERBOARD.items(), key=lambda x: x[1], reverse=True)[:5]
    txt = "🏆 Leaderboard:\n\n"
    for i, (ip, xp) in enumerate(top, 1):
        txt += f"{i}. User_{ip[-4:]} - {xp} XP\n"
    return jsonify({"reply": txt})

@app.route("/health")
def health():
    return "OK - Live"

# Vercel needs 'app' variable - this file IS the app
