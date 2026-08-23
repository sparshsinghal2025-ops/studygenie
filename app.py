from flask import Flask, render_template_string, request, jsonify, send_from_directory
from google import genai
from google.genai import types
import os, time

app = Flask(__name__, static_folder='static')
api_key = os.getenv("GEMINI_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)
active_users = {}

HTML = """
<!DOCTYPE html>
<html>
<head><title>StudyGenie by Sparsh Singhal</title><meta name="viewport" content="width=device-width, initial-scale=1"><script src="https://cdn.tailwindcss.com"></script><style>body{background:radial-gradient(circle at 20% 20%, #2a0a5e, #000); color:white; font-family:Inter,sans-serif;}.glass{backdrop-filter:blur(16px); background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.1); border-radius:18px;}.modal{position:fixed; inset:0; background:rgba(0,0,0,0.92); display:none; align-items:center; justify-content:center; z-index:9999;}.modal.active{display:flex;}</style></head>
<body>
<div class="glass m-3 p-3 flex items-center justify-between"><div class="flex items-center gap-3"><img src="/static/sparsh.jpg" onerror="this.src='/sparsh.jpg'; this.onerror=function(){this.src='https://i.pravatar.cc/100'}" class="w-14 h-14 rounded-full border-2 border-orange-500"><div><h1 class="text-[22px] font-black">StudyGenie <span class="text-orange-400">by Sparsh Singhal</span></h1><p class="text-xs opacity-70">Genie Bolega Ab ✨</p></div></div><div class="flex gap-2"><span class="bg-white/10 px-3 py-1 rounded-full text-xs" id="livePill">🔥 1 live</span><span id="streakTop" class="bg-orange-500/20 px-3 py-1 rounded-full text-xs border border-orange-500">🔥 1 streak</span></div></div>
<div class="flex flex-col lg:flex-row gap-4 p-3"><div class="flex-[7] flex flex-col gap-3"><div id="chat" class="glass p-4 min-h-[420px] flex flex-col gap-3 overflow-y-auto max-h-[65vh]"><div class="glass p-4">🧞‍♂️ <b>Hukm mere aaka! Mai Sparsh Singhal ka Genie hu, bolo kya seekhna hai?</b></div></div><div class="glass p-3 flex gap-3 items-center"><div class="bg-gradient-to-r from-purple-500 to-orange-500 px-4 py-1 rounded-full text-xs font-bold" id="levelBadge">Level 1</div><div class="flex-1 h-2 bg-black rounded-full"><div id="xpBar" style="width:10%" class="h-full bg-gradient-to-r from-orange-400 to-yellow-400"></div></div><span id="xpText" class="text-xs">0 XP</span></div><div class="glass p-2 flex gap-2"><input id="q" class="flex-1 bg-transparent outline-none p-3" placeholder="Pucho..."><button onclick="startMic()" class="bg-white/10 px-4 rounded-full">🎙️</button><button class="bg-gradient-to-r from-orange-500 to-red-500 px-8 rounded-full font-bold" onclick="ask()">GO →</button></div></div>
<div class="flex-[3] flex flex-col gap-3"><div class="glass p-4"><h3 class="font-bold">Wishes <span id="wishText" class="text-orange-400">0/10</span> <span id="founderTag" class="hidden text-[10px] bg-green-500/20 px-2 py-0.5 rounded-full ml-2 border border-green-500">DEV UNLIMITED</span></h3><div class="h-2 bg-black rounded-full mt-2"><div id="wishBar" style="width:0%" class="h-full bg-gradient-to-r from-purple-500 to-orange-500"></div></div><p class="text-xs mt-2 opacity-60" id="liveText">Only you is grinding 🔥</p></div><div class="glass p-3"><p class="text-sm">🔋 Battery <span id="bat">100%</span></p></div><div class="glass p-3"><p class="text-sm">🏆 Leaderboard #1</p><p class="text-[11px] opacity-70" id="boardText">You - 0 XP</p></div></div></div>
<div id="payModal" class="modal"><div class="glass w-[540px] bg-[#0d0820] p-6 text-center m-4 rounded-[28px] border-2 border-orange-500"><h2 class="text-3xl font-black">Aaka, Genie Thak Gaya! 🧞‍♂️💔</h2><p class="mt-3">10 Wishes khatam</p><button class="w-full bg-gradient-to-r from-orange-500 to-red-600 py-4 rounded-full font-black mt-4" onclick="location.href='/pay'">Charge Karo → 🚀</button><p class="mt-3"><a href="#" onclick="resetWishes(); return false;" class="text-xs opacity-60 underline">Testing Reset</a></p></div></div>
<script>
let today=new Date().toDateString(); let store=JSON.parse(localStorage.getItem("sg_final")||'{"c":0,"xp":0,"streak":1,"last":"","name":"","d":""}'); if(store.d!=today){let y=new Date(Date.now()-86400000).toDateString(); if(store.last==y) store.streak++; else if(store.last) store.streak=1; store.c=0; store.d=today;}
const WISH_LIMIT = 10;
const DEV_CODE = "genie2006";
function isFounder(){ return localStorage.getItem("sg_is_founder")==="true"; }
function updateUI(){ let founder = isFounder(); document.getElementById('founderTag').classList.toggle('hidden',!founder); if(founder){ document.getElementById('wishText').innerText='∞ Unlimited'; document.getElementById('wishBar').style.width='100%'; document.getElementById('wishBar').className='h-full bg-gradient-to-r from-green-500 to-emerald-400'; document.getElementById('bat').innerText='∞'; } else { document.getElementById('wishText').innerText=store.c+'/'+WISH_LIMIT; document.getElementById('wishBar').style.width=(store.c/WISH_LIMIT*100)+'%'; document.getElementById('bat').innerText=(100-store.c*10)+'%'; } document.getElementById('xpBar').style.width=(store.xp%100)+'%'; document.getElementById('xpText').innerText=store.xp+' XP'; document.getElementById('streakTop').innerText='🔥 '+store.streak+' streak'; document.getElementById('boardText').innerText=`You - ${store.xp} XP`; if(!founder && store.c>=WISH_LIMIT) document.getElementById('payModal').classList.add('active'); }
function resetWishes(){store.c=0; localStorage.setItem("sg_final", JSON.stringify(store)); document.getElementById('payModal').classList.remove('active'); updateUI();}

// FIXED - Pura bolega + Emoji nahi bolega
function speak(t){
  try{
    speechSynthesis.cancel();
    let clean = t.replace(/<[^>]*>/g,'')
               .replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F900}-\u{1F9FF}\u{1F600}-\u{1F64F}]/gu,'')
               .replace(/[🔥💡🧠🧞‍♂️😏😊😂💔🚀🎙️💡📚]/g,'')
               .replace(/\s+/g,' ').trim();
    if(!clean) return;
    let parts = clean.match(/[^.!?।]+[.!?।]+|[^.!?।]+$/g) || [clean];
    let i=0;
    function next(){
      if(i>=parts.length) return;
      let txt = parts[i].trim();
      if(txt){
        let u=new SpeechSynthesisUtterance(txt);
        u.lang='hi-IN'; u.rate=1.05;
        u.onend=()=>{i++; next();};
        speechSynthesis.speak(u);
      } else { i++; next(); }
    }
    next();
  }catch{}
}

async function ask(){
  let q=document.getElementById('q').value.trim(); if(!q) return;
  if(q.toLowerCase() === DEV_CODE){
    localStorage.setItem("sg_is_founder","true");
    document.getElementById('q').value="";
    alert("🔓 DEV MODE UNLOCKED! Ab tere liye unlimited hai.");
    updateUI();
    let chat=document.getElementById('chat');
    chat.innerHTML+=`<div class="glass p-3 text-sm border border-green-500">✅ Founder Verified - ∞ Unlimited Active</div>`;
    return;
  }
  if(q.toLowerCase() === "genielock"){ localStorage.setItem("sg_is_founder","false"); alert("Dev mode locked"); updateUI(); return; }
  if(!store.name){ let n=prompt("Aaka naam kya hai?"); if(!n) return; store.name=n.trim(); localStorage.setItem("sg_final", JSON.stringify(store)); }
  let founder = isFounder();
  if(!founder && store.c>=WISH_LIMIT){document.getElementById('payModal').classList.add('active'); return;}
  if(!founder) store.c++; store.xp+=12; store.last=today; localStorage.setItem("sg_final", JSON.stringify(store)); updateUI();
  let chat=document.getElementById('chat'); chat.innerHTML+=`<div class="self-end bg-gradient-to-r from-orange-500 to-red-500 p-3 rounded-2xl max-w-[80%] text-sm">${q}</div>`; document.getElementById('q').value=""; chat.innerHTML+=`<div class="glass p-3 text-sm" id="tmp">🧞‍♂️ Soch raha hu...</div>`; chat.scrollTop=chat.scrollHeight;
  try{let res=await fetch("/ask",{method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({q, name:store.name||'aaka'})}); let data=await res.json(); document.getElementById('tmp').remove(); chat.innerHTML+=`<div class="glass p-4 text-sm">🧞‍♂️ ${data.ans}<br><br><button onclick="speak(this.parentElement.innerText)" class="text-xs bg-white/10 px-3 py-1 rounded-full">🔊 Suno</button></div>`; speak(data.ans); chat.scrollTop=chat.scrollHeight;}catch{ document.getElementById('tmp').innerText="⚠️ Error"; }
}
function startMic(){let Rec=window.SpeechRecognition||window.webkitSpeechRecognition; if(!Rec){alert("Mic not supported"); return;} let rec=new Rec(); rec.lang='hi-IN'; rec.start(); rec.onresult=e=>{document.getElementById('q').value=e.results[0][0].transcript; ask();}}
setInterval(async()=>{try{let r=await fetch('/active'); let d=await r.json(); document.getElementById('livePill').innerText=d.count<=1?"🔥 1 live":"🔥 "+d.count+" live";}catch{}},3000);
updateUI();
</script></body></html>
"""
@app.route("/")
def home(): return render_template_string(HTML)
@app.route("/sparsh.jpg")
def sparsh_root():
    try: return send_from_directory(".", "sparsh.jpg")
    except: return send_from_directory("static", "sparsh.jpg")
@app.route("/static/<path:p>")
def static_files(p): return send_from_directory("static", p)
@app.route("/active")
def active():
    ip=request.remote_addr; active_users[ip]=time.time(); now=time.time(); live=len([1 for v in active_users.values() if now-v<90]);
    for k in list(active_users.keys()):
        if now-active_users[k]>90: del active_users[k]
    return jsonify({"count": max(1, live)})
@app.route("/ask", methods=["POST"])
def ask_route():
    d=request.json; q=d.get("q",""); name=d.get("name","aaka")
    prompt = f"You are StudyGenie by Sparsh Singhal, a funny alien genie. Explain '{q}' for {name} in Hinglish. Use EXACT format: 🔥 Definition (2 lines) \\n💡 Example (1 real life) \\n🧠 Feynman (simple story). Keep total under 150 words. End with 'Aur hukm {name}? 😏'"
    try:
        response = client.models.generate_content(model="gemini-3.6-flash", contents=prompt, config=types.GenerateContentConfig(max_output_tokens=2048, temperature=0.7))
        ans = response.text.replace("\\n","<br>")
    except Exception as e:
        ans = f"Arre {name}, error: {e}"
    return jsonify({"ans": ans})
@app.route("/pay")
def pay(): return "Razorpay Rs49 Integration - Coming Soon"
if __name__=="__main__": app.run(debug=True)
