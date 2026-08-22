from flask import Flask, request, render_template_string, jsonify
import os, random
from datetime import datetime
from groq import Groq
import google.generativeai as genai

# API Keys from Vercel
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
genai.configure(api_key=os.getenv("GEMINI_KEY"))
gemini_model = genai.GenerativeModel('gemini-1.5-flash')

app = Flask(__name__)

# Database
USERS = {}
BADGES = ["🔥 Beginner", "⭐ Explorer", "🚀 Pro", "👑 Legend"]
LEADERBOARD = {}

def get_user(ip):
    today = str(datetime.now().date())
    if ip not in USERS:
        USERS[ip] = {"xp":0, "streak":1, "last_day":today, "badges":[BADGES[0]], "lang":"hinglish"}
    u = USERS[ip]
    if u["last_day"]!= today:
        u["streak"] += 1
        u["last_day"] = today
    return u

def ai_answer(topic, mins, lang="hinglish"):
    prompts = {
        "1": f"Explain '{topic}' in {lang}, 3 lines only, 1 trick for exam. Very short.",
        "5": f"Explain '{topic}' in {lang}: 5 points, 1 example, 1 trick to remember. Medium.",
        "10": f"Explain '{topic}' in {lang} full masterclass: definition, types, example with code if needed, 2 common mistakes, 2 interview Qs. Detailed."
    }
    prompt = prompts.get(mins, prompts["5"])
    try:
        res = groq_client.chat.completions.create(model="llama-3.1-8b-instant", messages=[{"role":"user","content":prompt}])
        return res.choices[0].message.content
    except Exception as e:
        try:
            res = gemini_model.generate_content(prompt)
            return res.text
        except:
            return f"AI busy hai: {str(e)[:100]}"

HTML_PAGE = """
<!DOCTYPE html>
<html><head><meta name="viewport" content="width=device-width, initial-scale=1">
<title>StudyGenie V2 - Sparsh</title>
<style>
body{background:#000;color:#fff;font-family:system-ui;text-align:center;padding:20px}
input{width:90%;max-width:500px;padding:14px;border-radius:12px;border:none;font-size:16px}
button{padding:10px 18px;margin:6px;border-radius:20px;background:#fff;color:#000;border:none;font-weight:bold;cursor:pointer}
.card{background:#121212;padding:18px;border-radius:16px;margin:20px auto;max-width:650px;text-align:left;white-space:pre-wrap;border:1px solid #222}
.top{display:flex;justify-content:center;gap:12px;flex-wrap:wrap;margin:15px}
.pill{background:#1a1a1a;padding:8px 14px;border-radius:20px;font-size:14px}
</style></head>
<body>
<h1>StudyGenie 🔥 by Sparsh Singhal </h1>
<div class="top">
<span class="pill" id="s">🔥 Streak: {{streak}} din</span>
<span class="pill" id="x">⭐ XP: {{xp}} | {{badge}}</span>
<span class="pill" id="l">🏆 Best: {{top}} XP</span>
</div>
<input id="topic" placeholder="Topic likho e.g. Recursion">
<br><br>
<button onclick="ask('1')">/1min ⚡</button>
<button onclick="ask('5')">/5min 🧠</button>
<button onclick="ask('10')">/10min 👑</button>
<br>
<button onclick="callApi('/api/daily')">/daily 📅</button>
<button onclick="callApi('/api/leaderboard')">/leaderboard 🏆</button>
<button onclick="doMood()">/mood 😔</button>
<button onclick="doHelp()">/help ❓</button>
<div id="ans" class="card">Topic likh ke 1/5/10 Min dabaa... Jadoo yaha ayega!</div>
<script>
function ask(m){
 let t=document.getElementById('topic').value; if(!t){alert('Topic likh bhai!');return}
 document.getElementById('ans').innerText='Soch raha hu... ✨';
 fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({topic:t,min:m})})
.then(r=>r.json()).then(d=>{
  document.getElementById('ans').innerText=d.reply;
  document.getElementById('s').innerText='🔥 Streak: '+d.streak+' din';
  document.getElementById('x').innerText='⭐ XP: '+d.xp+' | '+d.badge;
 })
}
function callApi(url){ fetch(url).then(r=>r.json()).then(d=>{document.getElementById('ans').innerText=d.reply})}
function doMood(){ let m=prompt('Mood bata: demotivated / bored / tired'); if(!m) return; fetch('/api/mood',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mood:m})}).then(r=>r.json()).then(d=>{document.getElementById('ans').innerText=d.reply})}
function doHelp(){ document.getElementById('ans').innerText='/1min /5min /10min - Topic samjho\\n/bhasha hindi - Language badlo\\n/xp - Level dekho\\n/streak - Roz aane ka inaam\\n/daily - Aaj ka mission\\n/leaderboard - Topper kaun?\\n/mood - Motivation\\n/badge - Apne badges dekho\\n\\nMade with ❤️ by Sparsh Singhal'}
</script></body></html>
"""

@app.route("/")
def home():
    u=get_user(request.remote_addr)
    top = max(LEADERBOARD.values()) if LEADERBOARD else 0
    return render_template_string(HTML_PAGE, streak=u["streak"], xp=u["xp"], badge=u["badges"][-1], top=top)

@app.route("/api/ask", methods=["POST"])
def api_ask():
    data=request.get_json(); topic=data.get("topic",""); mins=data.get("min","1")
    u=get_user(request.remote_addr); u["xp"]+=10*int(mins); LEADERBOARD[request.remote_addr]=u["xp"]
    if u["xp"]>=100 and BADGES[1] not in u["badges"]: u["badges"].append(BADGES[1])
    if u["xp"]>=300 and BADGES[2] not in u["badges"]: u["badges"].append(BADGES[2])
    if u["xp"]>=600 and BADGES[3] not in u["badges"]: u["badges"].append(BADGES[3])
    return jsonify({"reply":ai_answer(topic, mins, u["lang"]), "streak":u["streak"], "xp":u["xp"], "badge":u["badges"][-1]})

@app.route("/api/daily")
def daily(): return jsonify({"reply": f"📅 DAILY MISSION: {random.choice(['Arrays ke 2 Qs solve kar','1 DBMS topic revise kar','Linked List dry run kar','SQL ke 5 commands yaad kar'])} - Kar ke 50 XP le!"})

@app.route("/api/leaderboard")
def lb():
    top = sorted(LEADERBOARD.items(), key=lambda x:x[1], reverse=True)[:3]
    if not top: return jsonify({"reply":"Abhi koi topper nahi, tu first ban ja! 🔥"})
    txt="🏆 LEADERBOARD TOP 3:\n"
    for i,(ip,xp) in enumerate(top,1): txt+=f"{i}. User..{ip[-4:]} - {xp} XP\n"
    return jsonify({"reply":txt})

@app.route("/api/mood", methods=["POST"])
def mood():
    m=request.get_json().get("mood","").lower()
    msgs={"demotivated":"Sparsh bhi 2 baar fail hua tha bhai. Bas 5 min padh, streak mat tod. Tu kar lega! 💪","bored":"Bored? Chal 1 Min me kuch naya seekhte hain. Koi bhi topic likh.","tired":"Thak gaya? 10 min rest kar, fir 1 topic hi padh. Ho jayega."}
    return jsonify({"reply": msgs.get(m, "Tu sher hai bhai! Bas 1 aur topic. 🔥")})

@app.route("/webhook", methods=["POST"])
def webhook(): return jsonify({"reply":"V2 live"})

@app.route("/health")
def health(): return "OK"
