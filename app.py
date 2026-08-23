from flask import Flask, render_template_string, request, jsonify, send_from_directory
from google import genai
from google.genai import types
import os, time

app = Flask(__name__, static_folder='static')

# AQ wali key ke liye naya client
api_key = os.getenv("GEMINI_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

active_users = {}

HTML = """
<!DOCTYPE html>
<html>
<head>
<title>StudyGenie by Sparsh Singhal - Genie Bolega Ab</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/canvas-confetti@1.9.2/dist/confetti.browser.min.js"></script>
<style>
body{background:radial-gradient(circle at 20% 20%, #2a0a5e, #000); color:white; font-family:Inter,sans-serif;}
.glass{backdrop-filter:blur(16px); background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.1); border-radius:18px;}
.modal{position:fixed; inset:0; background:rgba(0,0,0,0.92); backdrop-filter:blur(15px); display:none; align-items:center; justify-content:center; z-index:9999;}
.modal.active{display:flex;}
</style>
</head>
<body>
<div class="glass m-3 p-3 flex items-center justify-between">
  <div class="flex items-center gap-3">
    <img src="/static/sparsh.jpg" onerror="this.src='/sparsh.jpg'; this.onerror=function(){this.src='https://i.pravatar.cc/100'}" class="w-14 h-14 rounded-full border-2 border-orange-500 object-cover">
    <div>
      <h1 class="text-[22px] font-black">StudyGenie <span class="text-orange-400">by Sparsh Singhal</span></h1>
      <p class="text-xs opacity-70">Built by Sparsh Singhal • <span class="text-orange-300">Genie Bolega Ab ✨</span></p>
    </div>
  </div>
  <div class="flex gap-2 items-center">
    <span class="bg-white/10 px-3 py-1 rounded-full text-xs" id="livePill">🔥 1 live</span>
    <span id="streakTop" class="bg-orange-500/20 px-3 py-1 rounded-full text-xs border border-orange-500">🔥 1 streak</span>
  </div>
</div>
<div class="flex flex-col lg:flex-row gap-4 p-3">
  <div class="flex-[7] flex flex-col gap-3">
    <div id="chat" class="glass p-4 min-h-[420px] flex flex-col gap-3 overflow-y-auto max-h-[65vh]">
      <div class="glass p-4">🧞‍♂️ <b>Hukm mere aaka! Mai Sparsh Singhal ka Genie hu, bolo kya seekhna hai?</b><br><span class="text-xs opacity-50">Tip: Bol ke pucho, mai bol ke bataunga 🔊</span></div>
    </div>
    <div class="glass p-3 flex gap-3 items-center">
      <div class="bg-gradient-to-r from-purple-500 to-orange-500 px-4 py-1 rounded-full text-xs font-bold" id="levelBadge">Level 1 • Genie ka Chela</div>
      <div class="flex-1 h-2 bg-black rounded-full"><div id="xpBar" style="width:10%" class="h-full bg-gradient-to-r from-orange-400 to-yellow-400 transition-all"></div></div>
      <span id="xpText" class="text-xs">0 XP</span>
    </div>
    <div class="glass p-2 flex gap-2">
      <input id="q" class="flex-1 bg-transparent outline-none p-3" placeholder="Pucho ya bolo... 'arrays samjhao'">
      <button onclick="startMic()" class="bg-white/10 px-4 rounded-full">🎙️</button>
      <button class="bg-gradient-to-r from-orange-500 to-red-500 px-8 rounded-full font-bold" onclick="ask()">GO →</button>
    </div>
  </div>
  <div class="flex-[3] flex flex-col gap-3">
    <div class="glass p-4">
      <h3 class="font-bold">Wishes <span id="wishText" class="text-orange-400">0/5</span></h3>
      <div class="h-2 bg-black rounded-full mt-2"><div id="wishBar" style="width:0%" class="h-full bg-gradient-to-r from-purple-500 to-orange-500"></div></div>
      <p class="text-xs mt-2 opacity-60" id="liveText">Only you is grinding 🔥 • ⏳ <span id="timer">10:36</span></p>
    </div>
    <div class="glass p-3"><p class="text-sm">🔋 Battery <span id="bat">100%</span> • <span class="text-xs opacity-60">Healthy</span></p></div>
    <div class="glass p-3"><p class="text-sm">🏆 Leaderboard #<span id="rank">1</span></p><p class="text-[11px] opacity-70" id="boardText">You - 0 XP • Be the first topper!</p></div>
    <div class="glass p-3"><div class="grid grid-cols-2 gap-2 text-xs"><button class="glass py-2" onclick="quick('Feynman style me samjha')">💡 Feynman</button><button class="glass py-2" onclick="quick('meme banao iska')">😂 Meme</button><button class="glass py-2" onclick="quick('interview Qs de')">💼 Interview</button><button class="glass py-2 bg-orange-500/20" onclick="startMic()">🎙️ Bol Ke Puch</button></div></div>
    <div class="glass p-3 flex gap-2 items-center"><img src="/static/sparsh.jpg" onerror="this.src='/sparsh.jpg'" class="w-8 h-8 rounded-full"><p class="text-xs">Founder's Touch • Built by Sparsh Singhal<br><span class="opacity-50">v1.4 - Genie Bolega Ab</span></p></div>
  </div>
</div>
<div id="payModal" class="modal"><div class="glass w-[540px] bg-[#0d0820] p-6 text-center m-4 rounded-[28px] border-2 border-orange-500"><h2 class="text-3xl font-black">Aaka, Genie Thak Gaya! 🧞‍♂️💔</h2><p class="mt-3">5 Wishes khatam, ab charge karo Genie ko</p><button class="w-full bg-gradient-to-r from-orange-500 to-red-600 py-4 rounded-full font-black mt-4" onclick="location.href='/pay'">Haan, Charge Karo → 🚀</button><p class="mt-3"><a href="#" onclick="document.getElementById('payModal').classList.remove('active')" class="text-xs opacity-30 underline">Nahi, mera streak delete kar do</a></p></div></div>
<script>
let today=new Date().toDateString();
let store=JSON.parse(localStorage.getItem("sg_final")||'{"c":0,"xp":0,"streak":1,"last":"","name":"","d":""}');
if(store.d!=today){let y=new Date(Date.now()-86400000).toDateString(); if(store.last==y) store.streak++; else if(store.last) store.streak=1; store.c=0; store.d=today;}
function updateUI(){document.getElementById('wishBar').style.width=(store.c/5*100)+'%'; document.getElementById('wishText').innerText=store.c+'/5'; document.getElementById('xpBar').style.width=(store.xp%100)+'%'; document.getElementById('xpText').innerText=store.xp+' XP'; document.getElementById('streakTop').innerText='🔥 '+store.streak+' streak'; document.getElementById('bat').innerText=(100-store.c*18)+'%'; document.getElementById('boardText').innerText=`You - ${store.xp} XP • Keep going!`; if(store.c>=5) document.getElementById('payModal').classList.add('active');}
function speak(t){try{speechSynthesis.cancel(); let u=new SpeechSynthesisUtterance(t.replace(/<[^>]*>/g,'').slice(0,300)); u.lang='hi-IN'; u.rate=1.05; speechSynthesis.speak(u);}catch{}}
function quick(t){document.getElementById('q').value=t; ask();}
async function ask(){
  let q=document.getElementById('q').value.trim(); if(!q) return;
  if(!store.name){let n=prompt("Aaka naam kya hai?"); if(n) store.name=n;}
  if(store.c>=5){document.getElementById('payModal').classList.add('active'); return;}
  store.c++; store.xp+=12; store.last=today; localStorage.setItem("sg_final", JSON.stringify(store)); updateUI();
  let chat=document.getElementById('chat');
  chat.innerHTML+=`<div class="self-end bg-gradient-to-r from-orange-500 to-red-500 p-3 rounded-2xl max-w-[80%] text-sm">${q}</div>`;
  document.getElementById('q').value="";
  chat.innerHTML+=`<div class="glass p-3 text-sm" id="tmp">🧞‍♂️ Soch raha hu ${store.name||'aaka'}...</div>`;
  chat.scrollTop=chat.scrollHeight;
  try{
    let res=await fetch("/ask",{method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({q, name:store.name||'aaka'})});
    let data=await res.json();
    document.getElementById('tmp').remove();
    chat.innerHTML+=`<div class="glass p-4 text-sm">🧞‍♂️ ${data.ans}<br><br><button onclick="speak(this.parentElement.innerText)" class="text-xs bg-white/10 px-3 py-1 rounded-full">🔊 Suno</button></div>`;
    speak(data.ans); chat.scrollTop=chat.scrollHeight;
  }catch{ document.getElementById('tmp').innerText="⚠️ Genie thak gaya, fir se try karo"; }
}
function startMic(){let Rec=window.SpeechRecognition||window.webkitSpeechRecognition; if(!Rec){alert("Mic not supported"); return;} let rec=new Rec(); rec.lang='hi-IN'; rec.start(); rec.onresult=e=>{document.getElementById('q').value=e.results[0][0].transcript; ask();}}
setInterval(async()=>{try{let r=await fetch('/active'); let d=await r.json(); let c=d.count; document.getElementById('livePill').innerText=c<=1?"🔥 1 live":"🔥 "+c+" live"; document.getElementById('liveText').innerText=c<=1?"Only you is grinding 🔥":""+c+" log abhi padh rahe hai";}catch{}},3000);
updateUI();
</script>
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HTML)

@app.route("/sparsh.jpg")
def sparsh_root():
    try: return send_from_directory(".", "sparsh.jpg")
    except: return send_from_directory("static", "sparsh.jpg")

@app.route("/static/<path:p>")
def static_files(p):
    return send_from_directory("static", p)

@app.route("/active")
def active():
    ip = request.remote_addr
    active_users[ip] = time.time()
    now = time.time()
    live = len([1 for v in active_users.values() if now - v < 90])
    for k in list(active_users.keys()):
        if now - active_users[k] > 90: del active_users[k]
    return jsonify({"count": max(1, live)})

# YAHAN FIX HAI - CUT NAHI HOGA AB
@app.route("/ask", methods=["POST"])
def ask_route():
    d = request.json
    q = d.get("q","")
    name = d.get("name","aaka")
    prompt = f"You are StudyGenie by Sparsh Singhal. User {name} asks: {q}. Answer in Hinglish, 180-220 words. Structure: 🔥Def -> 💡Example -> 🧠Feynman. Be funny alien genie. End with 'Aur hukm {name}? 😏'"
    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=1000,
                temperature=0.8
            )
        )
        ans = response.text.replace("\n","<br>")
    except Exception as e:
        ans = f"Arre {name}, error: {e}"
    return jsonify({"ans": ans})

@app.route("/pay")
def pay():
    return "Razorpay Rs49 Integration - StudyGenie by Sparsh Singhal"

if __name__ == "__main__":
    app.run(debug=True)
