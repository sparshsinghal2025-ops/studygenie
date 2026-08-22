from flask import Flask, request, render_template_string, jsonify, send_from_directory
import os, random
from datetime import datetime
import google.generativeai as genai

# API Key setup
genai.configure(api_key=os.getenv("GEMINI_KEY"))

app = Flask(__name__)

# User data
USERS = {}
BADGES = ["🔥 Beginner", "⭐ Explorer", "🚀 Pro", "👑 Legend"]
LEADERBOARD = {}

def get_user(ip):
    today = str(datetime.now().date())
    if ip not in USERS:
        USERS[ip] = {"xp":0, "streak":1, "last_day":today, "badges":[BADGES[0]]}
    u = USERS[ip]
    if u["last_day"]!= today:
        u["streak"] += 1
        u["last_day"] = today
    return u

def ai_answer(topic, mins):
    prompts = {
        "1": f"Explain '{topic}' in Hinglish in 3 short lines + 1 super trick for exam. Very short, to the point.",
        "5": f"Explain '{topic}' in Hinglish: 5 points, 1 real example, 1 trick to remember. Medium length.",
        "10": f"Explain '{topic}' in Hinglish full masterclass: definition, types, example with code if needed, 2 common mistakes students make, 2 interview Qs with answers. Detailed but simple."
    }
    prompt = prompts.get(mins, prompts["5"])

    # PERMANENT FIX - Auto model finder
    MODEL_LIST = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-1.5-flash-latest",
        "gemini-1.5-flash-001",
        "gemini-pro",
        "models/gemini-1.5-flash"
    ]

    for model_name in MODEL_LIST:
        try:
            model = genai.GenerativeModel(model_name)
            res = model.generate_content(prompt)
            if res and res.text:
                return res.text
        except Exception as e:
            continue

    return "AI thoda busy hai bhai, 30 sec baad fir se try kar. Tension nahi lene ka! 💪"

# FINAL HTML - With Brand
HTML_PAGE = """
<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>StudyGenie - By Sparsh Singhal</title>
<style>
body{background:#000;color:#fff;font-family:system-ui;text-align:center;padding:20px;margin:0}
input{width:90%;max-width:500px;padding:15px;border-radius:12px;border:none;font-size:16px;outline:none}
button{padding:12px 20px;margin:6px;border-radius:25px;background:#fff;color:#000;border:none;font-weight:bold;cursor:pointer;transition:0.2s}
button:active{transform:scale(0.95)}
.card{background:#121212;padding:18px;border-radius:16px;margin:20px auto;max-width:650px;text-align:left;white-space:pre-wrap;border:1px solid #222;line-height:1.6}
.top{display:flex;justify-content:center;gap:12px;flex-wrap:wrap;margin:20px}
.pill{background:#1a1a1a;padding:10px 16px;border-radius:20px;font-size:14px;border:1px solid #222}
.brand{background:linear-gradient(135deg,#111,#1c1c1c);padding:25px;border-radius:20px;max-width:650px;margin:40px auto;border:1px solid #333}
.brand img{width:110px;height:110px;border-radius:50%;border:3px solid #fff;object-fit:cover;background:#222}
.brand h2{margin:12px 0 6px 0}
.brand p{color:#aaa;font-size:14px;line-height:1.6}
</style></head>
<body>
<h1 style="margin-bottom:5px">StudyGenie 🔥</h1>
<p style="color:#666;margin-top:0;font-size:13px">By Sparsh Singhal - Coaching Killer</p>

<div class="top">
<span class="pill" id="s">🔥 Streak: {{streak}} din</span>
<span class="pill" id="x">⭐ XP: {{xp}} | {{badge}}</span>
</div>

<input id="topic" placeholder="Topic likho e.g. OOPS, Recursion, DBMS">
<br><br>
<button onclick="ask('1')">⚡ 1 Min</button>
<button onclick="ask('5')">🧠 5 Min</button>
<button onclick="ask('10')">👑 10 Min</button>
<br>
<button onclick="callApi('/api/daily')" style="background:#222;color:#fff;border:1px solid #333">📅 /daily</button>
<button onclick="callApi('/api/leaderboard')" style="background:#222;color:#fff;border:1px solid #333">🏆 /leaderboard</button>
<button onclick="mood()" style="background:#222;color:#fff;border:1px solid #333">💬 /mood</button>

<div id="ans" class="card">Topic likh ke button dabaa - jadoo dekhega! ✨</div>

<div class="brand">
<img src="/sparsh.jpg" onerror="this.src='https://i.imgur.com/8Km9tLL.png'">
<h2>Sparsh Singhal 👑</h2>
<p style="color:#fff;font-weight:bold;margin:5px">Founder - StudyGenie</p>
<p>12th fail se coder tak ka safar. Masai School se seekha, ab mission hai 1 lakh bachcho ko bina coaching ke top karwana. Ye bot nahi, tumhara bhai hai jo roz tumhare saath padhega.</p>
<p style="font-size:12px;color:#555;margin-top:15px">Made with ❤️ in India | StudyGenie V2.0 - Permanent Edition</p>
</div>

<script>
function ask(m){
 let t=document.getElementById('topic').value;
 if(!t){alert('Pehle topic toh likh bhai! 😅');return}
 document.getElementById('ans').innerText='Sparsh ka Genie soch raha hai... ✨ thoda wait...';
 fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({topic:t,min:m})})
.then(r=>r.json()).then(d=>{
  document.getElementById('ans').innerText=d.reply;
  document.getElementById('s').innerText='🔥 Streak: '+d.streak+' din';
  document.getElementById('x').innerText='⭐ XP: '+d.xp+' | '+d.badge;
 })
}
function callApi(url){
 document.getElementById('ans').innerText='Loading...';
 fetch(url).then(r=>r.json()).then(d=>{document.getElementById('ans').innerText=d.reply})
}
function mood(){
 let m=prompt('Mood bata: demotivated / bored / tired');
 if(!m) return;
 fetch('/api/mood',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mood:m})})
.then(r=>r.json()).then(d=>{document.getElementById('ans').innerText=d.reply})
}
</script>
</body></html>
"""

@app.route("/")
def home():
    u=get_user(request.remote_addr)
    return render_template_string(HTML_PAGE, streak=u["streak"], xp=u["xp"], badge=u["badges"][-1])

@app.route("/sparsh.jpg")
def photo():
    try:
        return send_from_directory('.', 'sparsh.jpg')
    except:
        return "", 404

@app.route("/api/ask", methods=["POST"])
def api_ask():
    d=request.get_json()
    topic=d.get("topic","")
    mins=d.get("min","1")
    u=get_user(request.remote_addr)
    u["xp"]+=10*int(mins)
    LEADERBOARD[request.remote_addr]=u["xp"]
    if u["xp"]>=100 and BADGES[1] not in u["badges"]: u["badges"].append(BADGES[1])
    if u["xp"]>=300 and BADGES[2] not in u["badges"]: u["badges"].append(BADGES[2])
    if u["xp"]>=600 and BADGES[3] not in u["badges"]: u["badges"].append(BADGES[3])
    return jsonify({"reply":ai_answer(topic, mins), "streak":u["streak"], "xp":u["xp"], "badge":u["badges"][-1]})

@app.route("/api/daily")
def daily():
    tasks = ["Arrays ke 2 Questions solve kar", "DBMS - Indexing revise kar", "Linked List Dry Run kar", "SQL ke 5 commands yaad kar", "OOPS ke 4 pillars revise kar"]
    return jsonify({"reply": f"📅 AAJ KA MISSION: {random.choice(tasks)}\nComplete karke 50 XP lele!"})

@app.route("/api/leaderboard")
def lb():
    top = sorted(LEADERBOARD.items(), key=lambda x:x[1], reverse=True)[:5]
    if not top: return jsonify({"reply":"Abhi koi topper nahi hai, tu pehla ban! 🚀"})
    txt="🏆 LEADERBOARD - TOP 5 STUDENTS:\n\n"
    for i,(ip,xp) in enumerate(top,1):
        txt+=f"{i}....{ip[-4:]} - {xp} XP\n"
    return jsonify({"reply":txt})

@app.route("/api/mood", methods=["POST"])
def mood_api():
    m=request.get_json().get("mood","").lower()
    msgs={
        "demotivated":"Bhai Sparsh bhi 12th me fail hua tha. Aaj dekh kaha hai. Tu bhi kar lega. Bas 5 min padh le, bas 5 min! 💪",
        "bored":"Bore ho raha hai? Chal /1min wala game khelte hain. Ek topic likh, 1 min me khatam!",
        "tired":"Thak gaya? 10 min aankh band kar, pani pee, fir ek chota topic kar lete hain. Ho jayega!"
    }
    return jsonify({"reply": msgs.get(m, "Tu sher hai bhai! Bas laga reh. 🔥")})

@app.route("/health")
def health(): return "OK - StudyGenie Permanent Edition Running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
