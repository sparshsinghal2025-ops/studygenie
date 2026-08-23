import os
from flask import Flask, request, jsonify, send_from_directory, render_template_string
from google import genai

app = Flask(__name__)
API_KEY = os.environ.get("GOOGLE_API_KEY", "")
client = genai.Client(api_key=API_KEY) if API_KEY else None
REAL_LEADERBOARD = {}

HTML_PAGE = """
<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>StudyGenie by Sparsh Singhal</title>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@500;700;900&family=Space+Grotesk:wght@700&display=swap" rel="stylesheet">
<style>
*{font-family:'Outfit',sans-serif}
body{background:#050507!important; overflow-x:hidden; color:white}
.bg-orb{position:fixed; border-radius:50%; filter:blur(90px); pointer-events:none; z-index:-1}
.glass{background: rgba(18,18,32,0.88)!important; backdrop-filter:blur(24px); border:1px solid rgba(255,122,0,0.15)!important; box-shadow: 0 8px 32px rgba(0,0,0,0.6)}
.bubble-user{background: linear-gradient(135deg, #ff6a00, #ff9900); box-shadow: 0 8px 20px rgba(255,106,0,0.4)}
.bubble-ai{background: #141422; border:1px solid #2a2a4a}
.lamp{transition:0.4s cubic-bezier(.34,1.56,.64,1)}.lamp.off{filter:grayscale(1) opacity(0.25); transform:scale(0.8)}
.float{animation:float 3s ease-in-out infinite} @keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}
.glow{box-shadow:0 0 25px rgba(255,153,0,0.5)}
.custom-scroll::-webkit-scrollbar{width:4px}.custom-scroll::-webkit-scrollbar-thumb{background:#ff6a00; border-radius:10px}
</style>
</head>
<body class="p-2 md:p-4">
<div class="bg-orb w-[700px] h-[700px] bg-[#ff6a00] opacity-[0.12] -top-40 -left-40"></div>
<div class="bg-orb w-[600px] h-[600px] bg-[#7c3aed] opacity-[0.10] -bottom-20 -right-20"></div>

<div class="glass rounded-[20px] px-4 py-3 flex justify-between items-center max-w-[1400px] mx-auto">
  <div class="flex items-center gap-3">
    <div class="relative"><img id="logo" src="/sparsh.jpg" class="w-11 h-11 rounded-[14px] border-2 border-orange-400 object-cover cursor-pointer glow"><div class="absolute -bottom-1 -right-1 w-4 h-4 bg-green-400 rounded-full border-2 border-black animate-pulse"></div></div>
    <div>
      <h1 class="font-black text-[18px] leading-none" style="font-family:'Space Grotesk'">StudyGenie <span class="text-orange-400">by Sparsh Singhal</span></h1>
      <div class="flex items-center gap-2 mt-1"><span class="text-[11px] px-2 py-0.5 rounded-full bg-orange-500/20 border border-orange-500/30">🔥 <span id="streak">3</span> Day Streak</span><span id="devBadge" class="hidden text-[10px] bg-yellow-400 text-black px-2 py-0.5 rounded-full font-black">DEV 👑 UNLIMITED</span></div>
    </div>
  </div>
  <div class="flex items-center gap-2">
    <div class="hidden md:flex items-center gap-1 glass px-3 py-1.5 rounded-full"><span class="text-xs">✨</span><span id="wishLeft" class="text-xs font-black">10</span><span class="text-[10px] opacity-60">wishes</span></div>
    <button id="voiceBtn" onclick="toggleVoice()" class="px-3 py-2 rounded-full text-xs font-bold bg-[#1e1e32] border border-white/10">🔊 ON</button>
  </div>
</div>

<div class="grid grid-cols-1 lg:grid-cols-12 gap-4 max-w-[1400px] mx-auto mt-4">
  <div class="lg:col-span-8 glass rounded-[28px] p-3 md:p-5 flex flex-col h-[78vh] md:h-[82vh]">
    <div id="chat" class="flex-1 overflow-y-auto space-y-4 pr-1">
      <div class="flex gap-3"><div class="w-8 h-8 rounded-full bg-gradient-to-br from-orange-400 to-yellow-400 flex items-center justify-center text-sm shrink-0">🧞</div><div class="bubble-ai p-4 rounded-[20px] rounded-tl-[4px] max-w-[88%] text-[14px] leading-[1.6]"><b class="text-orange-400">Yo aaka! Sparsh ka Genie hazir hai! 🔮</b><br><br>10 jadooi chiraag mile hain, har sawal pe ek jalega. Khatam hue toh Genie Pro ban jaunga! <br><br><span class="text-xs opacity-70">💻 Coding = Code + Dry Run<br>📖 Theory = Trick + Hack<br>🤖 Auto-detect ON!</span></div></div>
    </div>
    <div class="flex gap-2 mt-3 overflow-x-auto pb-1">
      <button onclick="quickAsk('Linked List samjha de masti me')" class="shrink-0 bg-[#1e1e32] hover:bg-orange-500/20 border border-white/10 px-3 py-2 rounded-full text-xs">💻 Linked List = Code</button>
      <button onclick="quickAsk('Photosynthesis easy trick')" class="shrink-0 bg-[#1e1e32] border border-white/10 px-3 py-2 rounded-full text-xs">🌿 Photosynthesis</button>
      <button onclick="quickAsk('Ek joke suna Genie style')" class="shrink-0 bg-[#1e1e32] border border-white/10 px-3 py-2 rounded-full text-xs">😂 Joke</button>
      <button onclick="quickAsk('Mera roast kar')" class="shrink-0 bg-[#1e1e32] border border-white/10 px-3 py-2 rounded-full text-xs">🔥 Roast Me</button>
    </div>
    <div class="mt-3 glass rounded-full p-1.5 flex items-center gap-2 bg-[#0f0f1a]"><input id="q" class="flex-1 bg-transparent px-4 py-2.5 outline-none text-[14px] placeholder-white/30" placeholder="Boliye mere aaka, kya chahiye... ✨" onkeypress="if(event.key==='Enter')ask()"><button onclick="ask()" class="bg-white text-black w-10 h-10 rounded-full font-black hover:scale-105 transition">→</button></div>
  </div>

  <div class="lg:col-span-4 space-y-4">
    <div class="glass rounded-[22px] p-4">
      <div class="flex justify-between items-center"><h3 class="font-black text-sm">🧞 Wishes</h3><span id="wishes" class="text-xs font-bold bg-black/40 px-2 py-1 rounded-full">0 / 10</span></div>
      <div id="lampRow" class="grid grid-cols-5 gap-2 mt-4"></div>
      <div class="h-2 bg-black/50 rounded-full mt-4 overflow-hidden"><div id="wishBar" class="h-full bg-gradient-to-r from-orange-500 to-yellow-400 transition-all duration-700" style="width:0%"></div></div>
      <p class="text-[11px] mt-2 opacity-50">10 ke baad Genie Pro ₹49 me 💸</p>
    </div>
    <div class="glass rounded-[22px] p-4">
      <h3 class="font-black text-sm flex justify-between">🏆 Live Leaderboard <span class="text-[8px] bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 px-2 py-0.5 rounded-full">LIVE REAL</span></h3>
      <div id="board" class="mt-3 space-y-1.5"><p class="text-xs opacity-40">Tu pehla grinder hai 🔥</p></div>
    </div>
    <div class="glass rounded-[22px] p-4 relative overflow-hidden">
      <div class="absolute w-24 h-24 bg-orange-500/20 blur-[20px] rounded-full -right-5 -top-5"></div>
      <div class="flex justify-between"><h3 class="font-bold text-sm">⚡ Level <span id="lvl">1</span></h3><span id="xpText" class="text-xs opacity-60">0 XP</span></div>
      <div class="flex items-center gap-3 mt-3">
        <div class="w-12 h-12 rounded-full border-[3px] border-orange-500/30 flex items-center justify-center font-black text-sm" id="levelRing">1</div>
        <div class="flex-1"><div class="h-2.5 bg-black/50 rounded-full overflow-hidden"><div id="xpBar" class="h-full bg-gradient-to-r from-yellow-300 to-orange-500 transition-all" style="width:10%"></div></div><p class="text-[10px] mt-1 opacity-50"><span id="xp">0</span> / 100 XP</p></div>
      </div>
    </div>
  </div>
</div>

<!-- 28 FEATURES PRO MODAL ₹49 -->
<div id="payModal" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4" style="background:rgba(0,0,0,0.88); backdrop-filter:blur(18px)">
  <div class="glass rounded-[28px] p-6 max-w-[420px] w-full border border-orange-500/25 text-center flex flex-col max-h-[90vh]">
    <div class="w-16 h-16 mx-auto rounded-[18px] bg-gradient-to-br from-orange-400 to-yellow-400 flex items-center justify-center text-2xl shadow-[0_0_30px_rgba(255,153,0,0.5)] shrink-0">🧞‍♂️</div>
    <h2 class="mt-4 text-[22px] font-black leading-tight">Arre aaka, chiraag<br>khatam ho gaye! 🪔</h2>
    <p class="text-[13px] opacity-70 mt-2">10 free wishes done. Ab Pro bano toh ye 28 powers milengi 👇</p>
    <div class="mt-4 bg-black/50 rounded-[16px] p-4 text-left text-[12px] space-y-2 border border-white/5 overflow-y-auto max-h-[38vh] custom-scroll">
      <div class="flex gap-2">✅ <b>Unlimited</b> wishes - No limit</div>
      <div class="flex gap-2">✅ <b>Voice</b> full speed + Hindi+English</div>
      <div class="flex gap-2">✅ <b>Top</b> leaderboard boost & badge</div>
      <div class="flex gap-2">✅ <b>PDF Upload</b> - Notes se direct Q/A</div>
      <div class="flex gap-2">✅ <b>Image Doubt</b> - Photo kheecho, solution lo</div>
      <div class="flex gap-2">✅ <b>Code Execution</b> - Python/C++ run inside</div>
      <div class="flex gap-2">✅ <b>Dry Run Visualizer</b> - Animation</div>
      <div class="flex gap-2">✅ <b>Memory Retention</b> - Genie yaad rakhega</div>
      <div class="flex gap-2">✅ <b>Personal Notes</b> - Auto summary</div>
      <div class="flex gap-2">✅ <b>Flashcards</b> - 1-click revision</div>
      <div class="flex gap-2">✅ <b>Mock Tests</b> - Daily 10Q test</div>
      <div class="flex gap-2">✅ <b>Trick Generator</b> - Har theory ka jugaad</div>
      <div class="flex gap-2">✅ <b>Roast Mode Pro</b> - Ultra savage</div>
      <div class="flex gap-2">✅ <b>Joke + Meme</b> - Study break</div>
      <div class="flex gap-2">✅ <b>No Ads</b> - Clean Genie</div>
      <div class="flex gap-2">✅ <b>Priority Speed</b> - 2x fast answers</div>
      <div class="flex gap-2">✅ <b>Doubt Chain</b> - Follow-up unlimited</div>
      <div class="flex gap-2">✅ <b>Formula Sheet</b> - Auto PDF export</div>
      <div class="flex gap-2">✅ <b>Chapter Wise</b> - Class 6-12 mapping</div>
      <div class="flex gap-2">✅ <b>PYQ Solver</b> - Previous year papers</div>
      <div class="flex gap-2">✅ <b>Code Optimizer</b> - TLE se bachao</div>
      <div class="flex gap-2">✅ <b>Error Finder</b> - Bug dhoonde</div>
      <div class="flex gap-2">✅ <b>Concept Map</b> - Mindmap banega</div>
      <div class="flex gap-2">✅ <b>Voice Doubt</b> - Bolo, Genie sunega</div>
      <div class="flex gap-2">✅ <b>Share Chat</b> - Dosto ko bhejo</div>
      <div class="flex gap-2">✅ <b>Streak Freeze</b> - 1 din miss maaf</div>
      <div class="flex gap-2">✅ <b>Dark Pro Theme</b> - Neon Genie</div>
      <div class="flex gap-2">✅ <b>Sparsh Support</b> - Direct founder chat</div>
    </div>
    <button onclick="buyPro()" class="w-full mt-5 bg-white text-black font-black py-3.5 rounded-full shrink-0">Unlock All 28 Powers - ₹49/month 🚀</button>
    <button onclick="closePay()" class="w-full mt-2 text-xs opacity-50 py-2 shrink-0">Abhi nahi</button>
    <p class="text-[10px] mt-2 opacity-30 shrink-0">Dev? Logo pe 5x tap = free unlock</p>
  </div>
</div>

<script>
let voiceOn=true, synth=window.speechSynthesis, queue=[], isSpeaking=false;
let userId = localStorage.getItem('genie_userId') || 'user_'+Math.random().toString(36).substr(2,9);
localStorage.setItem('genie_userId', userId);
let stats = JSON.parse(localStorage.getItem('genie_stats') || '{"xp":0,"level":1,"wishes":0,"streak":3}');
let isDev = localStorage.getItem('isDev')==='true';
function lamps(){
  let row=document.getElementById('lampRow'); row.innerHTML='';
  for(let i=0;i<10;i++){
    let used = i < stats.wishes &&!isDev;
    row.innerHTML+=`<div class="lamp ${used?'off':''} w-8 h-8 rounded-[10px] bg-gradient-to-br from-orange-400 to-yellow-300 flex items-center justify-center text-[14px] shadow-lg">${used?'💨':'🔥'}</div>`;
  }
}
function save(){localStorage.setItem('genie_stats', JSON.stringify(stats)); render();}
function render(){
  document.getElementById('wishes').innerText = isDev? stats.wishes+' / ∞' : stats.wishes+' / 10';
  document.getElementById('wishLeft').innerText = isDev? '∞' : Math.max(0,10-stats.wishes);
  document.getElementById('lvl').innerText = stats.level;
  document.getElementById('levelRing').innerText = stats.level;
  document.getElementById('xp').innerText = stats.xp;
  document.getElementById('xpText').innerText = stats.xp + (stats.level-1)*100 + ' XP';
  document.getElementById('streak').innerText = stats.streak;
  document.getElementById('wishBar').style.width = isDev? '100%' : (stats.wishes*10)+'%';
  document.getElementById('xpBar').style.width = stats.xp+'%';
  document.getElementById('devBadge').classList.toggle('hidden',!isDev);
  lamps(); loadBoard();
}
async function loadBoard(){
  try{
    let r=await fetch('/leaderboard?uid='+userId); let d=await r.json();
    if(!d.length){document.getElementById('board').innerHTML='<div class="text-xs opacity-40 p-2">Tu pehla grinder hai! 🔥</div>'; return;}
    let html=''; d.slice(0,5).forEach((u,i)=>{
      let isMe = u.id===userId;
      let medal = i==0?'🥇':i==1?'🥈':i==2?'🥉':`#${i+1}`;
      html+=`<div class="flex justify-between items-center px-2 py-2 rounded-[12px] ${isMe?'bg-orange-500/20 border border-orange-500/30 text-orange-300': 'bg-black/20'}"><span class="text-xs">${medal} ${u.name} ${isMe?'(You)':''} ${isMe && isDev?'👑':''}</span><span class="text-[11px] font-bold">${u.xp} XP</span></div>`;
    });
    document.getElementById('board').innerHTML=html;
  }catch{}
}
let c=0; document.getElementById('logo').addEventListener('click',()=>{c++; if(c>=5){isDev=!isDev; localStorage.setItem('isDev',isDev); alert(isDev?'DEV MODE ON 👑 Unlimited':'DEV OFF'); c=0; render();} setTimeout(()=>c=0,2000);});
function toggleVoice(){voiceOn=!voiceOn; document.getElementById('voiceBtn').innerText=voiceOn?'🔊 ON':'🔇 OFF'; if(!voiceOn){synth.cancel(); queue=[]; isSpeaking=false;}}
function clean(t){return t.replace(/<[^>]*>/g,'').replace(/[*#_`~]/g,'').replace(/[\\u{1F600}-\\u{1F6FF}]/gu,'').trim();}
function speakQueue(t){if(!voiceOn) return; let s=clean(t).match(/[^.!?]+[.!?]+|[\\s\\S]{1,140}(?=\\s|$)/g)||[clean(t)]; queue.push(...s); if(!isSpeaking) playNext();}
function playNext(){if(!queue.length){isSpeaking=false; return;} isSpeaking=true; let u=new SpeechSynthesisUtterance(queue.shift()); u.lang='hi-IN'; u.rate=1.05; u.onend=()=>playNext(); u.onerror=()=>playNext(); synth.speak(u);}
function closePay(){document.getElementById('payModal').classList.add('hidden');}
function buyPro(){alert("Pro - ₹49/month! Razorpay yahan lagega"); closePay();}
function quickAsk(t){document.getElementById('q').value=t; ask();}
async function ask(){
  let input=document.getElementById('q'); let q=input.value.trim(); if(!q) return;
  if(!isDev && stats.wishes>=10){document.getElementById('payModal').classList.remove('hidden'); return;}
  let chat=document.getElementById('chat');
  chat.innerHTML+=`<div class="flex justify-end"><div class="bubble-user px-4 py-3 rounded-[18px] rounded-br-[4px] max-w-[80%] text-[13px] font-medium">${q}</div></div>`; input.value='';
  stats.wishes++; stats.xp+=12; if(stats.xp>=100){stats.level++; stats.xp=0;} save();
  fetch('/update_xp',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({uid:userId, xp:(stats.level-1)*100+stats.xp, level:stats.level})});
  chat.innerHTML+=`<div id="typing" class="flex gap-3"><div class="w-8 h-8 rounded-full bg-[#1a1a2e] flex items-center justify-center">🧞</div><div class="bubble-ai px-4 py-3 rounded-[18px] text-xs opacity-60">Genie type kar raha hai...</div></div>`; chat.scrollTop=chat.scrollHeight;
  let res=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({q})}); let data=await res.json();
  document.getElementById('typing')?.remove();
  let id=Date.now(); chat.innerHTML+=`<div class="flex gap-3"><div class="w-8 h-8 rounded-full bg-gradient-to-br from-orange-400 to-yellow-400 flex items-center justify-center text-[12px] shrink-0">🧞</div><div class="bubble-ai p-4 rounded-[18px] rounded-tl-[4px] max-w-[88%] text-[13px] leading-relaxed whitespace-pre-wrap"><span id="ans-${id}">${data.ans}</span><div class="mt-3 flex gap-2"><button onclick="speakQueue(document.getElementById('ans-${id}').innerText)" class="text-[11px] bg-white/10 px-3 py-1 rounded-full">🔊 Suna de</button><button onclick="navigator.clipboard.writeText(document.getElementById('ans-${id}').innerText)" class="text-[11px] bg-white/10 px-3 py-1 rounded-full">📋 Copy</button></div></div></div>`;
  chat.scrollTop=chat.scrollHeight; speakQueue(data.ans);
}
render(); setInterval(loadBoard,5000);
</script></body></html>
"""
@app.route("/")
def home(): return render_template_string(HTML_PAGE)
@app.route("/sparsh.jpg")
def photo(): return send_from_directory(".", "sparsh.jpg")
@app.route("/static/<path:p>")
def static_files(p):
    try: return send_from_directory("static", p)
    except: return send_from_directory(".", p)
@app.route("/leaderboard")
def leaderboard():
    return jsonify(sorted(REAL_LEADERBOARD.values(), key=lambda x: x['xp'], reverse=True)[:10])
@app.route("/update_xp", methods=["POST"])
def update_xp():
    d=request.json; uid=d.get("uid"); REAL_LEADERBOARD[uid]={"id":uid,"name":f"Grinder {uid[-3:].upper()}","xp":d.get("xp",0),"level":d.get("level",1)}
    return jsonify({"ok":True})
@app.route("/ask", methods=["POST"])
def ask_gemini():
    q=request.json.get("q","")
    if not client: return jsonify({"ans":"API Key missing!"})
    try:
        resp=client.models.generate_content(model="gemini-3.6-flash", contents=f"You are StudyGenie by Sparsh, Gen-Z Hinglish Genie, funny, max 180 words. User: {q}")
        return jsonify({"ans":resp.text})
    except Exception as e: return jsonify({"ans":f"Error {e}"})
if __name__=="__main__": app.run()
