from flask import Flask, request, render_template_string, jsonify, send_from_directory
import os
from datetime import datetime
import random
from google import genai

app = Flask(__name__)

# New SDK client
def get_client():
    key = os.getenv("GEMINI_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        return None
    return genai.Client(api_key=key)

USERS, LEADERBOARD = {}, {}
BADGES = ["🔥 Beginner", "⭐ Explorer", "🚀 Pro", "👑 Legend"]

def get_user(ip):
    today=str(datetime.now().date())
    if ip not in USERS: USERS[ip]={"xp":0,"streak":1,"last_day":today,"badges":[BADGES[0]]}
    u=USERS[ip]
    if u["last_day"]!=today: u["streak"]+=1; u["last_day"]=today
    return u

def ai_answer(topic, mins):
    client = get_client()
    if not client:
        return "❌ GEMINI_KEY Vercel me nahi mila!"

    prompts={
        "1": f"Explain '{topic}' in Hinglish in 3 lines + 1 super trick.",
        "5": f"Explain '{topic}' in Hinglish: 5 points, 1 example, 1 trick.",
        "10": f"Explain '{topic}' in Hinglish full masterclass: definition, types, example with code if needed, 2 mistakes, 2 interview Qs."
    }
    prompt = prompts.get(mins, prompts["5"])

    try:
        # New SDK call - supports AQ. keys
        res = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )
        return res.text
    except Exception as e:
        return f"ERROR: {str(e)[:600]}"

HTML_PAGE = """<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>StudyGenie - By Sparsh Singhal</title><style>body{background:#000;color:#fff;font-family:system-ui;text-align:center;padding:20px;margin:0}input{width:90%;max-width:500px;padding:15px;border-radius:12px;border:none;font-size:16px}button{padding:12px 20px;margin:6px;border-radius:25px;background:#fff;color:#000;border:none;font-weight:bold;cursor:pointer}.card{background:#121212;padding:18px;border-radius:16px;margin:20px auto;max-width:650px;text-align:left;white-space:pre-wrap;border:1px solid #222;line-height:1.6}.top{display:flex;justify-content:center;gap:12px;flex-wrap:wrap;margin:20px}.pill{background:#1a1a1a;padding:10px 16px;border-radius:20px;font-size:14px;border:1px solid #222}.brand{background:linear-gradient(135deg,#111,#1c1c1c);padding:25px;border-radius:20px;max-width:650px;margin:40px auto;border:1px solid #333}.brand img{width:110px;height:110px;border-radius:50%;border:3px solid #fff;object-fit:cover}</style></head><body><h1>StudyGenie 🔥</h1><p style="color:#666;font-size:13px">By Sparsh Singhal - Coaching Killer</p><div class="top"><span class="pill" id="s">🔥 Streak: {{streak}} din</span><span class="pill" id="x">⭐ XP: {{xp}} | {{badge}}</span></div><input id="topic" placeholder="Topic likho e.g. OOPS"><br><br><button onclick="ask('1')">⚡ 1 Min</button><button onclick="ask('5')">🧠 5 Min</button><button onclick="ask('10')">👑 10 Min</button><br><button onclick="callApi('/api/daily')" style="background:#222;color:#fff;border:1px solid #333">📅 /daily</button><button onclick="callApi('/api/leaderboard')" style="background:#222;color:#fff;border:1px solid #333">🏆 /leaderboard</button><div id="ans" class="card">Topic likh ke button dabaa - ab pakka chalega! ✨</div><div class="brand"><img src="/sparsh.jpg" onerror="this.src='https://i.imgur.com/8Km9tLL.png'"><h2>Sparsh Singhal 👑</h2><p style="color:#fff;font-weight:bold">Founder - StudyGenie</p><p>12th fail se coder tak. Mission: 1 lakh bachcho ko bina coaching top karwana.</p><p style="font-size:11px;color:#555">V3.0 - New GenAI SDK (AQ. Key Support)</p></div><script>function ask(m){let t=document.getElementById('topic').value;if(!t){alert('Topic likh!');return}document.getElementById('ans').innerText='Genie soch raha hai... ✨';fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({topic:t,min:m})}).then(r=>r.json()).then(d=>{document.getElementById('ans').innerText=d.reply;document.getElementById('s').innerText='🔥 Streak: '+d.streak+' din';document.getElementById('x').innerText='⭐ XP: '+d.xp+' | '+d.badge;})}function callApi(u){document.getElementById('ans').innerText='Loading...';fetch(u).then(r=>r.json()).then(d=>{document.getElementById('ans').innerText=d.reply})}</script></body></html>"""

@app.route("/")
def home(): u=get_user(request.remote_addr); return render_template_string(HTML_PAGE, streak=u["streak"], xp=u["xp"], badge=u["badges"][-1])
@app.route("/sparsh.jpg")
def photo():
    try: return send_from_directory('.', 'sparsh.jpg')
    except: return "", 404
@app.route("/api/ask", methods=["POST"])
def api_ask():
    d=request.get_json(); u=get_user(request.remote_addr); u["xp"]+=10*int(d.get("min","1")); LEADERBOARD[request.remote_addr]=u["xp"]
    return jsonify({"reply":ai_answer(d.get("topic",""), d.get("min","1")), "streak":u["streak"], "xp":u["xp"], "badge":u["badges"][-1]})
@app.route("/api/daily")
def daily(): return jsonify({"reply":f"📅 MISSION: {random.choice(['Arrays 2 Qs','DBMS','Linked List','SQL','OOPS'])} - 50 XP"})
@app.route("/api/leaderboard")
def lb():
    top=sorted(LEADERBOARD.items(), key=lambda x:x[1], reverse=True)[:5]
    if not top: return jsonify({"reply":"Abhi koi nahi, tu pehla ban! 🚀"})
    txt="🏆 LEADERBOARD:\n\n"
    for i,(ip,xp) in enumerate(top,1): txt+=f"{i}. {ip[-4:]} - {xp} XP\n"
    return jsonify({"reply":txt})
@app.route("/health")
def health(): return "OK V3"
if __name__ == "__main__": app.run(host="0.0.0.0", port=5000)
