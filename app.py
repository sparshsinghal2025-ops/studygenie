import os
from flask import Flask, request, jsonify, send_from_directory
app = Flask(__name__)

try:
    from google import genai
    API_KEY = os.environ.get("GOOGLE_API_KEY", "")
    client = genai.Client(api_key=API_KEY) if API_KEY else None
except:
    client = None

HTML_PAGE = r"""
<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>StudyGenie by Sparsh Singhal</title>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@800&display=swap" rel="stylesheet">
<style>
body{background:#050507!important;color:#fff;overflow-y:auto!important;min-height:100vh;background-image:radial-gradient(circle at 50% 0%,#1a1208 0%,#050507 60%)}
.mono{font-family:'JetBrains Mono',monospace}
.hud{background:rgba(17,17,19,0.96);border:1px solid #232326}
.bubble-user{background:#fff;color:#000;border-radius:14px 14px 2px 14px;font-weight:900}
.bubble-ai{background:#17171a;border-left:4px solid #ff4d00;border-radius:4px 16px 16px 16px}
.ammo{width:42px;height:52px;background:#121216;border:1px solid #2e2e33;border-radius:6px;display:flex;align-items:center;justify-content:center}
.ammo.used{opacity:.15;transform:scale(.9)}
.progress{height:12px;background:#0f0f11;border:1px solid #2a2a2e;transform:skew(-10deg);border-radius:2px;overflow:hidden}
.progress>div{height:100%;background:linear-gradient(90deg,#ff4d00,#ff8a00);box-shadow:0 0 10px #ff4d00}
#chat{max-height:62vh;overflow-y:auto!important;scroll-behavior:smooth}
.hitpop{animation:pop.3s cubic-bezier(.175,.885,.32,1.275)} @keyframes pop{0%{transform:scale(.6)}100%{transform:scale(1)}}
.shake{animation:shake.3s} @keyframes shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-5px)}75%{transform:translateX(5px)}}
</style>
</head>
<body class="p-3">
<div id="main" class="max-w-[1450px] mx-auto pb-20">
<div class="hud rounded-[16px] px-5 py-3 flex justify-between items-center sticky top-2 z-30">
  <div class="flex items-center gap-6">
    <img id="logo" src="/sparsh.jpg" class="w-28 h-28 rounded-[16px] border-[4px] border-[#ff4d00] object-cover shadow-[0_0_40px_rgba(255,77,0,0.7)] cursor-pointer hitpop">
    <div><h1 class="font-black text-[22px] tracking-widest">STUDYGENIE <span class="text-[#ff4d00]">: BATTLE</span></h1><p class="mono text-[12px] text-[#ff8a00] mt-1">BY SPARSH SINGHAL // FOUNDER</p><div class="flex items-center gap-3 mt-3"><span class="mono text-[10px] text-zinc-400">SHIELD</span><div class="w-40 progress"><div id="xpBarTop" style="width:0%"></div></div><span id="xpText" class="mono text-[11px] font-bold">0/100 XP</span></div><p class="mono text-[9px] text-zinc-600 mt-1">LVL <span id="lvlTop">1</span> // 5x LOGO = DEV LOCK</p></div>
  </div>
  <div class="mono text-right"><div class="text-[10px] text-zinc-500">AMMO</div><div class="font-black text-3xl"><span id="wishLeft">10</span>/10</div></div>
</div>

<div class="grid grid-cols-12 gap-3 mt-3">
  <div class="col-span-12 lg:col-span-3 space-y-3">
    <div class="hud rounded-[14px] p-4"><p class="mono text-[10px] text-zinc-500">> MISSIONS BY SPARSH SINGHAL</p><div class="mt-4 bg-black p-3 rounded-[10px] border-l-[3px] border-[#ff4d00]"><div class="flex justify-between mono text-[11px] font-bold"><span>ELIMINATE 3 DOUBTS</span><span id="q1t">0/3</span></div><div class="progress mt-2"><div id="q1b" style="width:0%"></div></div></div></div>
    <div class="hud rounded-[14px] p-4"><p class="mono text-[10px] text-zinc-500">> AMMO CRATE</p><div id="lampRow" class="grid grid-cols-5 gap-2 mt-3"></div><button onclick="openPay()" class="w-full mt-4 bg-[#ff4d00] mono font-black py-3 rounded-[10px] shadow-[0_0_20px_rgba(255,77,0,0.4)]">RELOAD - ₹49</button></div>
  </div>
  <div class="col-span-12 lg:col-span-9 hud rounded-[16px] p-4 flex flex-col">
    <div id="chat" class="flex-1 space-y-4 pr-2"></div>
    <div class="mt-4 bg-black border-2 border-[#2a2a2e] rounded-[12px] p-1.5 flex items-center gap-2 sticky bottom-2"><span class="mono text-xs px-2 text-[#ff4d00] font-black">></span><input id="q" class="flex-1 bg-transparent mono text-[14px] outline-none py-3 px-2" placeholder="ENTER COMMAND BY SPARSH SINGHAL..." onkeypress="if(event.key==='Enter')ask()"><button onclick="ask()" class="bg-[#ff4d00] mono font-black w-20 h-11 rounded-[10px]">FIRE 🔫</button></div>
  </div>
</div>
</div>

<div id="payModal" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4" style="background:rgba(0,0,0,0.9)"><div class="hud rounded-[20px] p-6 max-w-[400px] w-full text-center border-2 border-[#ff4d00]/50"><h2 class="font-black text-2xl">OUT OF AMMO!</h2><p class="mono text-[11px] mt-2 text-zinc-400">BY SPARSH SINGHAL</p><button onclick="closePay()" class="w-full mt-4 bg-zinc-800 py-3 rounded-[10px] mono font-black">CANCEL</button></div></div>

<script>
// ===== SOUND ENGINE BY SPARSH SINGHAL =====
let audioCtx;
function initAudio(){ if(!audioCtx) audioCtx = new (window.AudioContext||window.webkitAudioContext)(); }
function playSound(type){
  try{
    initAudio();
    let o=audioCtx.createOscillator(); let g=audioCtx.createGain();
    o.connect(g); g.connect(audioCtx.destination);
    if(type=='fire'){ o.frequency.value=900; o.type='square'; g.gain.setValueAtTime(0.4, audioCtx.currentTime); g.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime+0.12); o.start(); o.stop(audioCtx.currentTime+0.12); }
    if(type=='hit'){ o.frequency.value=500; o.type='sine'; g.gain.setValueAtTime(0.3, audioCtx.currentTime); g.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime+0.2); o.start(); o.stop(audioCtx.currentTime+0.2); }
    if(type=='level'){ o.frequency.value=600; o.type='sine'; g.gain.setValueAtTime(0.4, audioCtx.currentTime); o.frequency.linearRampToValueAtTime(1200, audioCtx.currentTime+0.5); g.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime+0.6); o.start(); o.stop(audioCtx.currentTime+0.6); }
    if(type=='empty'){ o.frequency.value=150; o.type='sawtooth'; g.gain.setValueAtTime(0.4, audioCtx.currentTime); g.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime+0.6); o.start(); o.stop(audioCtx.currentTime+0.6); }
    if(type=='click'){ o.frequency.value=800; o.type='triangle'; g.gain.setValueAtTime(0.2, audioCtx.currentTime); g.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime+0.1); o.start(); o.stop(audioCtx.currentTime+0.1); }
    if(type=='reload'){ o.frequency.value=300; o.type='sine'; g.gain.setValueAtTime(0.4, audioCtx.currentTime); o.frequency.linearRampToValueAtTime(800, audioCtx.currentTime+0.4); g.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime+0.5); o.start(); o.stop(audioCtx.currentTime+0.5); }
  }catch{}
}
function openPay(){ playSound('empty'); document.getElementById('payModal').classList.remove('hidden'); }
function closePay(){ playSound('click'); document.getElementById('payModal').classList.add('hidden'); }

let userId=localStorage.getItem('genie_userId')||'user_'+Math.random().toString(36).substr(2,9); localStorage.setItem('genie_userId',userId);
let stats=JSON.parse(localStorage.getItem('genie_stats')||'{"xp":0,"level":1,"wishes":0,"q1":0}');
let isDev=localStorage.getItem('isDev')==='true';
function lamps(){let r=document.getElementById('lampRow'); r.innerHTML=''; for(let i=0;i<10;i++){let u=i<stats.wishes&&!isDev; r.innerHTML+=`<div class="ammo ${u?'used':''}">${u?'💨':'🪔'}</div>`;}}
function save(){localStorage.setItem('genie_stats',JSON.stringify(stats)); render();}
function render(){document.getElementById('wishLeft').innerText=isDev?'∞':10-stats.wishes; document.getElementById('xpBarTop').style.width=stats.xp+'%'; document.getElementById('xpText').innerText=stats.xp+'/100 XP'; document.getElementById('q1t').innerText=stats.q1+'/3'; document.getElementById('q1b').style.width=stats.q1/3*100+'%'; lamps();}

let c=0;
document.getElementById('logo').addEventListener('click',()=>{
  playSound('click'); c++;
  if(c>=5){
    let p=prompt("DEV ACCESS BY SPARSH SINGHAL - Secret Code:");
    if(p==="sparsh123"){ isDev=!isDev; localStorage.setItem('isDev',isDev); playSound(isDev?'level':'empty'); alert(isDev?'GOD MODE ON - Welcome Founder Sparsh Singhal':'GOD MODE OFF'); render(); }
    else if(p!==null){ playSound('empty'); alert("ACCESS DENIED!"); }
    c=0;
  }
  setTimeout(()=>c=0,2000);
});

async function ask(){
  let input=document.getElementById('q'); let q=input.value.trim(); if(!q) return;
  if(!isDev && stats.wishes>=10){ openPay(); return; }
  playSound('fire');
  let chat=document.getElementById('chat');
  chat.innerHTML+=`<div class="flex justify-end hitpop"><div class="bubble-user px-4 py-2 text-[14px] mono">${q}</div></div>`;
  input.value='';
  stats.wishes++; stats.q1=Math.min(3,stats.q1+1); stats.xp+=12;
  if(stats.xp>=100){ stats.level++; stats.xp=0; playSound('level'); chat.innerHTML+=`<div class="text-center mono text-[#ff4d00] font-black text-[12px] py-2 hitpop">★★ LEVEL UP BY SPARSH SINGHAL - LVL ${stats.level} ★★</div>`; }
  save();
  document.getElementById('main').classList.add('shake'); setTimeout(()=>document.getElementById('main').classList.remove('shake'),300);
  chat.innerHTML+=`<div id="typing" class="flex gap-3"><img src="/sparsh.jpg" class="w-12 h-12 rounded-[10px] border-2 border-[#ff4d00] object-cover"><div class="bubble-ai p-4 mono text-[12px] text-zinc-400 animate-pulse">> SPARSH SINGHAL'S GENIE LOCKING TARGET...</div></div>`; chat.scrollTop=chat.scrollHeight;
  let res=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({q})}); let data=await res.json();
  document.getElementById('typing')?.remove(); playSound('hit');
  chat.innerHTML+=`<div class="flex gap-3 hitpop"><img src="/sparsh.jpg" class="w-12 h-12 rounded-[10px] border-2 border-[#ff4d00] object-cover shadow-[0_0_15px_rgba(255,77,0,0.5)]"><div class="bubble-ai p-4 max-w-[78%] text-[14px] whitespace-pre-wrap">${data.ans}<div class="mt-3 mono text-[10px] text-zinc-500"><span class="bg-[#ff4d00] text-white px-2 py-0.5 rounded-[4px]">BY SPARSH SINGHAL</span> HIT CONFIRMED +12 XP 🔫</div></div></div>`;
  chat.scrollTop=chat.scrollHeight;
}

// ===== NEW WELCOME LINE BY SPARSH SINGHAL =====
document.getElementById('chat').innerHTML=`<div class="flex gap-3 hitpop"><img src="/sparsh.jpg" class="w-12 h-12 rounded-[10px] border-2 border-[#ff4d00] object-cover shadow-[0_0_15px_rgba(255,77,0,0.5)]"><div class="bubble-ai p-5 max-w-[78%] text-[14px] leading-relaxed">🔥 <b>OYE WARRIOR, BATTLEFIELD ME SWAGAT HAI!</b><br><br>Main hoon <b>Sparsh Singhal ka StudyGenie</b> — tere har doubt ko headshot dunga.<br><br>👉 Pehla command daal, 12 XP le aur shield badha. Ammo 10 hai, uske baad pro lena padega.<br><br><span class="mono text-[10px] text-[#ff4d00]">BY SPARSH SINGHAL | SYSTEM ONLINE | SOUND ON 🔊</span></div></div>`;
render();
setTimeout(()=>{ playSound('reload'); }, 500);
</script></body></html>
"""

@app.route("/")
def home(): return HTML_PAGE

@app.route("/sparsh.jpg")
def photo():
    try: return send_from_directory(".", "sparsh.jpg")
    except: return "", 204

@app.route("/ask", methods=["POST"])
def ask_gemini():
    d = request.get_json(silent=True) or {}
    q = d.get("q","")
    if not client: return jsonify({"ans":"API Key missing - BY SPARSH SINGHAL"})
    try:
        resp = client.models.generate_content(model="gemini-3.6-flash", contents=f"You are StudyGenie by Sparsh Singhal, Hinglish savage, max 180 words, always say made by Sparsh Singhal. User: {q}")
        return jsonify({"ans": resp.text})
    except Exception as e: return jsonify({"ans": f"Error {e}"})

if __name__ == "__main__": app.run()
