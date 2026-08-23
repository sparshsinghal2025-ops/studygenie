from flask import Flask, render_template_string, request, jsonify, send_from_directory
import google.generativeai as genai
import os, time, random

app = Flask(__name__, static_folder='static')
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# FAST MODEL - 5x tez, isliye sochne ka time khatam
# Tu chahe toh yaha "gemini-3.6-flash" likh de, agar fail hua toh auto 8b pe aayega
try:
    model = genai.GenerativeModel("gemini-3.6-flash", generation_config={"temperature":0.75, "max_output_tokens":1000})
    print("Using 3.6-flash")
except:
    model = genai.GenerativeModel("gemini-1.5-flash-8b", generation_config={"temperature":0.75, "max_output_tokens":1000})
    print("Fallback to 8b fast")

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
    <img src="/static/sparsh.jpg" onerror="this.src='/sparsh.jpg'; this.onerror=function(){this.src='https://i.pravatar.cc/100'}"
         class="w-14 h-14 rounded-full border-2 border-orange-500 shadow-[0_0_25px_orange] object-cover">
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
      <div class="flex-1 h-2 bg-black rounded-full"><div id="xpBar" style="width:10%" class="h-full bg-gradient-to-r from-orange-400 to-yellow-400 transition-all duration-500"></div></div>
      <span id="xpText" class="text-xs">0 XP</span>
      <span id="rewardPop" class="hidden bg-yellow-400 text-black px-3 py-1 rounded-full text-xs font-black animate-bounce">🎁 +20 XP!</span>
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
      <div class="h-2 bg-black rounded-full mt-2"><div id="wishBar" style="width:0%" class="h-full bg-gradient-to-r from-purple-500 to-orange-500 transition-all"></div></div>
      <p class="text-xs mt-2 opacity-60" id="liveText">Only you is grinding 🔥 • ⏳ <span id="timer">12:00</span></p>
      <p class="text-[11px] mt-1 text-red-300 hidden" id="lossText">⚠️ Band kiya toh <span id="xpLost">0</span> XP gayab!</p>
    </div>
    <div class="glass p-3"><p class="text-sm">🔋 Battery <span id="bat">100%</span> • <span class="text-xs opacity-60">Healthy</span></p><p class="text-[11px] opacity-50 mt-1">Roz aao, Genie full charge rahega</p></div>
    <div class="glass p-3"><p class="text-sm">🏆 Leaderboard #<span id="rank">1</span> <span class="text-green-400 text-xs" id="rankUp"></span></p><p class="text-[11px] opacity-70" id="boardText">You - 0 XP • Be the first topper!</p></div>
    <div class="glass p-3">
      <div class="grid grid-cols-2 gap-2 text-xs">
        <button class="glass py-2 hover:bg-white/10" onclick="quick('Feynman style me samjha')">💡 Feynman</button>
        <button class="glass py-2 hover:bg-white/10" onclick="quick('meme banao iska')">😂 Meme</button>
        <button class="glass py-2 hover:bg-white/10" onclick="quick('interview Qs de')">💼 Interview</button>
        <button class="glass py-2 bg-orange-500/20 border border-orange-500" onclick="startMic()">🎙️ Bol Ke Puch</button>
      </div>
    </div>
    <div class="glass p-3 flex gap-2 items-center">
      <img src="/static/sparsh.jpg" onerror="this.src='/sparsh.jpg'" class="w-8 h-8 rounded-full object-cover">
      <p class="text-xs">Founder's Touch • Built by Sparsh Singhal<br><span class="opacity-50">v1.3.1 - Genie Bolega Ab</span></p>
    </div>
  </div>
</div>

<div id="payModal" class="modal">
  <div class="glass w-[540px] bg-[#0d0820] p-0 overflow-hidden m-4 rounded-[28px] border-2 border-orange-500/50 shadow-[0_0_70px_rgba(255,100,0,0.5)]">
    <div class="bg-gradient-to-r from-orange-500 to-red-600 p-4 text-center">
      <p class="text-xs tracking-[5px] font-black">GENIE KI LAST SAANS</p>
      <h2 class="text-3xl font-black">Aaka, Genie Thak Gaya! 🧞‍♂️💔</h2>
    </div>
    <div class="p-6 text-center">
      <div class="bg-red-500/10 border border-red-500/30 p-2 rounded-full text-xs font-bold text-red-300">⚠️ Band kiya toh <span id="xpLost2">0</span> XP + <span id="streakLost">1</span> din streak DELETE</div>
      <div class="flex justify-center gap-2 my-3"><span class="bg-white/10 px-3 py-1 rounded-full text-xs" id="liveText2">🟢 Only you grinding</span><span class="bg-red-500/20 px-3 py-1 rounded-full text-xs border border-red-500">⏳ Offer: <span id="timer2">12:00</span></span></div>
      <div class="text-left bg-black/50 p-4 rounded-xl text-[12.5px] leading-7">
        ✅ <b>Unlimited Wishes</b> - Pucho puchte jao<br>
        ✅ <b>Photo Kheecho Doubt Khatam</b><br>
        ✅ <b>Voice Genie by Sparsh Singhal</b><br>
        ✅ <b>Code Runner + Dry Run</b><br>
        ✅ <b>PDF / PPT / MindMap Export</b><br>
        ✅ <b>Mock Interview + ATS Resume</b><br>
        ✅ <b>1000+ Interview Qs + Roadmap</b>
      </div>
      <p class="text-4xl font-black mt-3">₹49<span class="text-sm font-normal">/month</span> <span class="bg-green-500 text-black text-[11px] px-2 py-1 rounded-full">93% OFF</span></p>
      <button class="w-full bg-gradient-to-r from-orange-500 to-red-600 py-4 rounded-full font-black text-lg mt-4" onclick="buy()">Haan, Genie Ko Charge Karo → 🚀</button>
      <p class="mt-3"><a href="#" onclick="closeM()" class="text-[11px] opacity-30 underline">Nahi, mera streak delete kar do</a></p>
    </div>
  </div>
</div>

<script>
let today=new Date().toDateString();
let store=JSON.parse(localStorage.getItem("sg_final")||'{"c":0,"xp":0,"streak":1,"last":"","name":"","d":""}');
if(store.d!=today){
  let y=new Date(Date.now()-86400000).toDateString();
  if(store.last==y) store.streak++; else if(store.last) store.streak=1;
  store.c=0; store.d=today;
}
function updateUI(){
  document.getElementById('wishBar').style.width=(store.c/5*100)+'%';
  document.getElementById('wishText').innerText=store.c+'/5';
  document.getElementById('xpBar').style.width=(store.xp%100)+'%';
  document.getElementById('xpText').innerText=store.xp+' XP';
  document.getElementById('xpLost').innerText=store.xp;
  document.getElementById('xpLost2').innerText=store.xp;
  document.getElementById('streakLost').innerText=store.streak;
  document.getElementById('streakTop').innerText='🔥 '+store.streak+' streak';
  document.getElementById('bat').innerText=(100-store.c*18)+'%';
  let lvl=Math.floor(store.xp/100)+1;
  let name=lvl<3?'Genie ka Chela':lvl<6?'Genie ka Yaar':'Aaka';
  document.getElementById('levelBadge').innerText='Level '+lvl+' • '+name;
  document.getElementById('rank').innerText=Math.max(1, 5 - Math.floor(store.xp/100));
  document.getElementById('boardText').innerText=`You - ${store.xp} XP ${store.xp>0?'• Keep going!':'• Be the first topper!'}`;
  if(store.c>=3) document.getElementById('lossText').classList.remove('hidden');
  if(store.c>=5) openM();
}
function openM(){document.getElementById('payModal').classList.add('active'); speak(`Aaka ${store.xp} XP bachane ke liye charge kar do`); confetti({particleCount:100});}
function closeM(){document.getElementById('payModal').classList.remove('active');}
function buy(){location.href="/pay";}
function speak(t){ try{speechSynthesis.cancel(); let u=new SpeechSynthesisUtterance(t.replace(/<[^>]*>/g,'').slice(0,280)); u.lang='hi-IN'; u.rate=1.05; speechSynthesis.speak(u);}catch{} }
function quick(t){document.getElementById('q').value=t; ask();}
async function ask(){
  let q=document.getElementById('q').value.trim(); if(!q) return;
  if(!store.name){ let n=prompt("Aaka naam kya hai?"); if(n) store.name=n; }
  if(store.c>=5){openM(); return;}
  store.c++; store.xp+=12; store.last=today; localStorage.setItem("sg_final", JSON.stringify(store)); updateUI();
  let chat=document.getElementById('chat');
  chat.innerHTML+=`<div class="self-end bg-gradient-to-r from-orange-500 to-red-500 p-3 rounded-2xl max-w-[80%] text-sm">${q}</div>`;
  document.getElementById('q').value="";
  chat.innerHTML+=`<div class="glass p-3 text-sm" id="tmp">🧞‍♂️ Soch raha hu ${store.name||'aaka'}...</div>`;
  chat.scrollTop=chat.scrollHeight;
  if(store.c%3==0){ document.getElementById('rewardPop').classList.remove('hidden'); confetti({particleCount:60}); store.xp+=20; setTimeout(()=>document.getElementById('rewardPop').classList.add('hidden'),3000); }
  try{
    let res=await fetch("/ask",{method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({q, name:store.name||'aaka'})});
    let data=await res.json();
    document.getElementById('tmp').remove();
    chat.innerHTML+=`<div class="glass p-4 text-sm">🧞‍♂️ ${data.ans}<br><br><button onclick="speak(this.parentElement.innerText)" class="text-xs bg-white/10 px-3 py-1 rounded-full">🔊 Suno</button></div>`;
    speak(data.ans); chat.scrollTop=chat.scrollHeight;
  }catch{ document.getElementById('tmp').innerText="⚠️ Genie thoda thak gaya, fir se try karo"; }
}
function startMic(){ let Rec=window.SpeechRecognition||window.webkitSpeechRecognition; if(!Rec){alert("Mic not supported"); return;} let rec=new Rec(); rec.lang='hi-IN'; rec.start(); rec.onresult=e=>{document.getElementById('q').value=e.results[0][0].transcript; ask();} }
// REAL LIVE TRACKING
setInterval(async()=>{
  try{
    let r=await fetch('/active'); let d=await r.json(); let c=d.count;
    let liveText = c<=1? "Only you is grinding 🔥" : c+" log abhi padh rahe hai";
    document.getElementById('livePill').innerText = c<=1? "🔥 1 live" : "🔥 "+c+" live";
    document.getElementById('liveText').innerHTML = liveText + ' • ⏳ <span id="timer">'+document.getElementById('timer').innerText+'</span>';
    document.getElementById('liveText2').innerText = c<=1? "🟢 Only you grinding" : "🟢 "+c+" log padh rahe";
  }catch{}
},3000);
let t=720; setInterval(()=>{t--; let m=Math.floor(t/60), s=t%60; let txt=`${m}:${s<10?'0':''}${s}`; let el=document.getElementById('timer'); if(el) el.innerText=txt; let el2=document.getElementById('timer2'); if(el2) el2.innerText=txt; if(t<=0) t=720;},1000);
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
    # REAL COUNT - no fake +124
    live = len([1 for v in active_users.values() if now - v < 90])
    for k in list(active_users.keys()):
        if now - active_users[k] > 90:
            del active_users[k]
    return jsonify({"count": max(1, live)})

@app.route("/ask", methods=["POST"])
def ask_route():
    d = request.json
    q = d.get("q","")
    name = d.get("name","aaka")
    prompt = f"You are StudyGenie by Sparsh Singhal. User {name} asks: {q}. Answer in Hinglish, short 120-180 words. Structure: 🔥Def -> 💡Example -> 🧠Feynman. Be funny alien genie. End with 'Aur hukm {name}? 😏'"
    try:
        ans = model.generate_content(prompt).text
        ans = ans.replace("\n","<br>")
    except Exception as e:
        ans = f"Arre {name}, thoda network slow hai, fir se puch? 😅<br><small>{e}</small>"
    return jsonify({"ans": ans})

@app.route("/pay")
def pay():
    return "Razorpay Rs49 Integration - StudyGenie by Sparsh Singhal"

if __name__ == "__main__":
    app.run(debug=True)
