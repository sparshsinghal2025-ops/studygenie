from flask import Flask, render_template_string, request, jsonify, send_from_directory
import google.generativeai as genai, os, time, random

app = Flask(__name__, static_folder='static')
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-3.6-flash", generation_config={"temperature":0.95, "max_output_tokens":8192})

active_users = {}

HTML = """
<!DOCTYPE html>
<html>
<head>
<title>StudyGenie by Sparsh Singhal - Genie Bolega Ab</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/canvas-confetti@1.9.2/dist/confetti.browser.min.js"></script>
<style>
body{background:radial-gradient(circle at 20% 20%, #2a0a5e, #000); color:white;}
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
      <p class="text-xs opacity-70 tracking-wide">Built by Sparsh Singhal • <span class="text-orange-300">Genie Bolega Ab ✨</span></p>
    </div>
  </div>
  <div class="flex gap-2 items-center">
    <span class="bg-white/10 px-3 py-1 rounded-full text-xs">🔥 <span id="liveCount">137</span> live</span>
    <span id="streakTop" class="bg-orange-500/20 px-3 py-1 rounded-full text-xs border border-orange-500">🔥 0 streak</span>
  </div>
</div>

<div class="flex flex-col lg:flex-row gap-4 p-3">
  <div class="flex-[7] flex flex-col gap-3">
    <div id="chat" class="glass p-4 min-h-[420px] flex flex-col gap-3 overflow-y-auto">
      <div class="glass p-4">🧞‍♂️ <b id="genieText">Hukm mere aaka! Mai Sparsh Singhal ka Genie hu, bolo kya seekhna hai?</b><br><span class="text-xs opacity-50">Tip: Bol ke pucho, mai bol ke bataunga 🔊</span></div>
    </div>
    <div class="glass p-3 flex gap-3 items-center">
      <div class="bg-gradient-to-r from-purple-500 to-orange-500 px-4 py-1 rounded-full text-xs font-bold" id="levelBadge">Level 1 • Genie ka Chela</div>
      <div class="flex-1 h-2 bg-black rounded-full"><div id="xpBar" style="width:10%" class="h-full bg-gradient-to-r from-orange-400 to-yellow-400"></div></div>
      <span id="xpText" class="text-xs">0 XP</span>
      <span id="rewardPop" class="hidden bg-yellow-400 text-black px-3 py-1 rounded-full text-xs font-black animate-bounce">🎁 20 XP!</span>
    </div>
    <div class="glass p-2 flex gap-2">
      <input id="q" class="flex-1 bg-transparent outline-none p-3" placeholder="Pucho ya bolo... 'Newton's law ko meme banao'">
      <button onclick="startMic()" class="bg-white/10 px-4 rounded-full">🎙️</button>
      <button class="bg-gradient-to-r from-orange-500 to-red-500 px-8 rounded-full font-bold" onclick="ask()">GO →</button>
    </div>
  </div>

  <div class="flex-[3] flex flex-col gap-3">
    <div class="glass p-4">
      <h3 class="font-bold">Wishes <span id="wishText" class="text-orange-400">0/5</span></h3>
      <div class="h-2 bg-black rounded-full mt-2"><div id="wishBar" style="width:0%" class="h-full bg-gradient-to-r from-purple-500 to-orange-500"></div></div>
      <p class="text-xs mt-2 opacity-60"><span id="liveCount2">137</span> log abhi padh rahe • ⏳ <span id="timer">12:00</span> left</p>
      <p class="text-[11px] mt-1 text-red-300 hidden" id="lossText">⚠️ Band kiya toh <span id="xpLost">0</span> XP gayab!</p>
    </div>
    <div class="glass p-3"><p class="text-sm">🔋 Battery <span id="bat">100%</span> • <span id="batSub" class="text-xs opacity-60">Healthy</span></p><p class="text-[11px] opacity-50 mt-1">Aaka, roz aao, Genie full charge rahega</p></div>
    <div class="glass p-3"><p class="text-sm">🏆 Leaderboard #<span id="rank">12</span> <span class="text-green-400 text-xs">▲ Top 3 me aao</span></p><p class="text-[11px] opacity-50">You - <span id="xpSmall">0</span> XP • Aarav - 980 XP</p></div>
    <div class="glass p-3">
      <div class="grid grid-cols-2 gap-2 text-xs">
        <button class="glass py-2" onclick="quick('Feynman style me samjha')">💡 Feynman</button>
        <button class="glass py-2" onclick="quick('meme banao')">😂 Meme</button>
        <button class="glass py-2" onclick="quick('interview Qs de')">💼 Interview</button>
        <button class="glass py-2 bg-orange-500/20 border-orange-500 border" onclick="startMic()">🎙️ Bol Ke Puch</button>
      </div>
    </div>
    <div class="glass p-3 flex gap-2 items-center bg-gradient-to-r from-orange-500/10 to-purple-500/10">
      <img src="/static/sparsh.jpg" onerror="this.src='/sparsh.jpg'" class="w-8 h-8 rounded-full">
      <p class="text-xs">Founder's Touch • Built by Sparsh Singhal<br><span class="opacity-50">Crafted for learners • v1.3.0</span></p>
    </div>
  </div>
</div>

<!-- ULTRA PAYWALL WITH EXTRA ADDICTION -->
<div id="payModal" class="modal">
  <div class="glass w-[540px] bg-[#0d0820] p-0 overflow-hidden m-4 rounded-[28px] border-2 border-orange-500/50 shadow-[0_0_70px_rgba(255,100,0,0.5)]">
    <div class="bg-gradient-to-r from-orange-500 to-red-600 p-4 text-center">
      <p class="text-xs tracking-[5px] font-black">GENIE KI LAST SAANS</p>
      <h2 class="text-3xl font-black">Aaka, Genie Thak Gaya! 🧞‍♂️💔</h2>
    </div>
    <div class="p-6 text-center">
      <div class="bg-red-500/10 border border-red-500/30 p-2 rounded-full text-xs font-bold text-red-300 animate-pulse">⚠️ Agar ab band kiya toh tere <span id="xpLost2">0</span> XP + <span id="streakLost">0</span> din ka streak + progress DELETE ho jayega</div>
      <div class="flex justify-center gap-2 my-3"><span class="bg-green-500/10 border border-green-500/20 px-3 py-1 rounded-full text-xs">🟢 <span id="liveCount3">137</span> log abhi padh rahe</span><span class="bg-red-500/20 px-3 py-1 rounded-full text-xs border border-red-500 animate-pulse">⏳ Offer: <span id="timer2">12:00</span> left</span></div>
      <div class="text-left bg-black/50 p-4 rounded-xl text-[12.5px] leading-7">
        ✅ <b>Unlimited Wishes</b> - Aaka pucho puchte jao<br>
        ✅ <b>Photo Kheecho Doubt Khatam</b> - 2 sec me solution<br>
        ✅ <b>Voice Genie by Sparsh Singhal</b> - Tu bolega Genie samjhega<br>
        ✅ <b>Code Runner + Dry Run Table</b> - Yahi code chala<br>
        ✅ <b>PDF / PPT / MindMap Export</b> - Raat ko padha subah topper notes<br>
        ✅ <b>Mock Interview + ATS Resume</b> - HR se pehle Genie se pass<br>
        ✅ <b>1000+ Interview Qs + Tera Roadmap</b> - 4 saal ka rasta 4 min me<br>
        <p class="text-center mt-3 opacity-60">...and <b>21 superpowers</b> jo free walo ko kabhi nahi milenge 🔒</p>
      </div>
      <p class="text-[11px] mt-3 bg-white/5 py-2 rounded-full">🔥 Tere jaise 3 logon ne abhi 2 min pehle Pro liya - tu piche reh jayega</p>
      <p class="text-xs opacity-40 line-through mt-2">₹499/month</p>
      <p class="text-4xl font-black">₹49<span class="text-sm font-normal">/month</span> <span class="bg-green-500 text-black text-[11px] px-2 py-1 rounded-full">93% OFF</span></p>
      <button class="w-full bg-gradient-to-r from-orange-500 to-red-600 py-4 rounded-full font-black text-lg mt-4 shadow-[0_0_20px_orange]" onclick="buy()">Haan, Genie Ko Charge Karo → 🚀</button>
      <p class="mt-3"><a href="#" onclick="closeM()" class="text-[11px] opacity-30 underline">Nahi, mujhe topper nahi banna, mera streak delete kar do</a></p>
    </div>
  </div>
</div>

<script>
let today=new Date().toDateString();
let store=JSON.parse(localStorage.getItem("sg_v4")||'{"c":0,"xp":0,"streak":0,"last":"","name":"","d":""}');
if(store.d!=today){
  let y=new Date(Date.now()-86400000).toDateString();
  if(store.last==y) store.streak++; else if(store.last) store.streak=1; else store.streak=1;
  store.c=0; store.d=today;
}
function updateUI(){
  let perc=(store.c/5)*100; document.getElementById('wishBar').style.width=perc+'%'; document.getElementById('wishText').innerText=store.c+'/5';
  let xpMod=store.xp%100; document.getElementById('xpBar').style.width=xpMod+'%';
  document.getElementById('xpText').innerText=store.xp+' XP'; document.getElementById('xpSmall').innerText=store.xp;
  document.getElementById('xpLost').innerText=store.xp; document.getElementById('xpLost2').innerText=store.xp;
  document.getElementById('streakLost').innerText=store.streak;
  document.getElementById('streakTop').innerText='🔥 '+store.streak+' streak';
  document.getElementById('bat').innerText=(100-store.c*18)+'%';
  let lvl=Math.floor(store.xp/100)+1; let name=lvl<3?'Genie ka Chela':lvl<6?'Genie ka Yaar':'Aaka';
  document.getElementById('levelBadge').innerText='Level '+lvl+' • '+name;
  document.getElementById('rank').innerText=Math.max(1,15-Math.floor(store.xp/40));
  if(store.c>=3) document.getElementById('lossText').classList.remove('hidden');
  if(store.c>=5) openM();
}
function openM(){document.getElementById('payModal').classList.add('active'); speak("Aaka meri battery khatam! "+store.xp+" XP bachane ke liye charge kar do!"); confetti({particleCount:120});}
function closeM(){document.getElementById('payModal').classList.remove('active');}
function buy(){location.href="/pay";}
function speak(t){ speechSynthesis.cancel(); let u=new SpeechSynthesisUtterance(t.replace(/<[^>]*>/g,'').slice(0,280)); u.lang='hi-IN'; u.rate=1.05; speechSynthesis.speak(u); }
function quick(t){document.getElementById('q').value=t; ask();}
async function ask(){
  let q=document.getElementById('q').value.trim(); if(!q) return;
  if(!store.name){ let n=prompt("Aaka naam kya hai? Sparsh Singhal ka Genie naam se bulayega 😏"); if(n) store.name=n; }
  if(store.c>=5){openM(); return;}
  store.c++; store.xp+=12; store.last=today; localStorage.setItem("sg_v4", JSON.stringify(store)); updateUI();
  let chat=document.getElementById('chat'); chat.innerHTML+=`<div class="self-end bg-gradient-to-r from-orange-500 to-red-500 p-3 rounded-2xl max-w-[80%]">${q}</div>`;
  document.getElementById('q').value=""; chat.innerHTML+=`<div class="glass p-3" id="tmp">🧞‍♂️ Sparsh ka Genie soch raha hai ${store.name||'aaka'}...</div>`;
  if(store.c%3==0){ document.getElementById('rewardPop').classList.remove('hidden'); confetti({particleCount:60}); store.xp+=20; setTimeout(()=>document.getElementById('rewardPop').classList.add('hidden'),3000); }
  let res=await fetch("/ask",{method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({q, name:store.name||'aaka'})});
  let data=await res.json(); document.getElementById('tmp').remove();
  chat.innerHTML+=`<div class="glass p-4">🧞‍♂️ ${data.ans}<br><br><button onclick="speak(\`${data.ans.replace(/`/g,'')}\`)" class="text-xs bg-white/10 px-3 py-1 rounded-full">🔊 Dubara Suno</button></div>`;
  speak(data.ans);
}
function startMic(){ let rec=new (window.SpeechRecognition||window.webkitSpeechRecognition)(); rec.lang='hi-IN'; rec.start(); rec.onresult=e=>{document.getElementById('q').value=e.results[0][0].transcript; ask();} }
setInterval(async()=>{ try{let r=await fetch('/active'); let d=await r.json(); ['liveCount','liveCount2','liveCount3'].forEach(id=>{let el=document.getElementById(id); if(el) el.innerText=d.count});}catch{} },3000);
let t=720; setInterval(()=>{t--; let m=Math.floor(t/60), s=t%60; let txt=`${m}:${s<10?'0':''}${s}`; ['timer','timer2'].forEach(id=>{let el=document.getElementById(id); if(el) el.innerText=txt}); if(t<=0) t=720;},1000);
updateUI();
</script>
</body>
</html>
"""

@app.route("/sparsh.jpg")
def sparsh_root():
    return send_from_directory(".", "sparsh.jpg")

@app.route("/static/<path:p>")
def stat(p):
    return send_from_directory("static", p)

@app.route("/")
def home(): return render_template_string(HTML)

@app.route("/active")
def active():
    ip=request.remote_addr; active_users[ip]=time.time()
    now=time.time(); live=len([1 for v in active_users.values() if now-v<120])
    for k in list(active_users.keys()):
        if now-active_users[k]>120: del active_users[k]
    return jsonify({"count": live + 124 + random.randint(8,20)})

@app.route("/ask", methods=["POST"])
def ask():
    d=request.json; q=d.get("q",""); name=d.get("name","aaka")
    prompt=f"You are StudyGenie by Sparsh Singhal, alien funny genie. User {name}. Question: {q}. Reply Hinglish funny, format: 🔥Def -> 💡Example -> 🧠Feynman -> 🎯Interview. Under 220 words. End with 'Aur hukm {name}? 😏 - Sparsh Singhal ka Genie'"
    ans=model.generate_content(prompt).text.replace("\n","<br>")
    return jsonify({"ans":ans})

@app.route("/pay")
def pay(): return "Razorpay Rs49 - StudyGenie by Sparsh Singhal"

if __name__=="__main__": app.run(debug=True)
