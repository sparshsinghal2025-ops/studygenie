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
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@800&family=Outfit:wght@800;900&display=swap" rel="stylesheet">
<style>
body{background:#050507!important; color:#fff; background-image: radial-gradient(circle at 50% 0%, #1a1208 0%, #050507 60%); overflow:hidden}
.mono{font-family:'JetBrains Mono',monospace}
.hud{background:rgba(17,17,19,0.95); border:1px solid #232326; backdrop-filter:blur(16px); box-shadow:0 0 0 1px rgba(255,77,0,0.1) inset}
.bubble-user{background:#fff; color:#000; border-radius:14px 14px 2px 14px; font-weight:900}
.bubble-ai{background:#17171a; border-left:4px solid #ff4d00; border-radius:4px 16px 16px 16px; box-shadow:0 10px 30px rgba(0,0,0,0.5)}
.ammo{width:42px; height:52px; background:linear-gradient(180deg,#222226,#121216); border:1px solid #2e2e33; border-radius:6px; display:flex; align-items:center; justify-content:center; font-size:20px; transition:0.2s}
.ammo.used{opacity:0.15; transform:scale(0.9)}
.progress{height:12px; background:#0f0f11; border:1px solid #2a2a2e; transform:skew(-10deg); border-radius:2px; overflow:hidden}
.progress>div{height:100%; background:linear-gradient(90deg,#ff4d00,#ff8a00); box-shadow:0 0 10px #ff4d00}
.shake{animation:shake 0.3s} @keyframes shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-4px)}75%{transform:translateX(4px)}}
.hitpop{animation:pop 0.4s cubic-bezier(.175,.885,.32,1.275)} @keyframes pop{0%{transform:scale(0.5)}100%{transform:scale(1)}}
</style>
</head>
<body class="p-3">
<div id="main" class="max-w-[1450px] mx-auto">
<div class="hud rounded-[16px] px-5 py-3 flex justify-between items-center">
  <div class="flex items-center gap-6">
    <img id="logo" src="/sparsh.jpg" class="w-28 h-28 rounded-[16px] border-[4px] border-[#ff4d00] object-cover shadow-[0_0_40px_rgba(255,77,0,0.7)] cursor-pointer hitpop">
    <div><h1 class="font-black text-[22px] tracking-widest leading-none">STUDYGENIE <span class="text-[#ff4d00]">: BATTLE</span></h1><p class="mono text-[12px] text-[#ff8a00] mt-1">BY SPARSH SINGHAL // FOUNDER</p><div class="flex items-center gap-3 mt-3"><span class="mono text-[10px] text-zinc-400">SHIELD</span><div class="w-40 progress"><div id="xpBarTop" style="width:0%"></div></div><span id="xpText" class="mono text-[11px] font-bold">0/100 XP</span></div><p class="mono text-[9px] text-zinc-600 mt-1">LVL <span id="lvlTop">1</span> // RANK #<span id="rankTop">?</span></p></div>
  </div>
  <div class="flex items-center gap-5"><div class="mono text-right"><div class="text-[10px] text-zinc-500 tracking-widest">AMMO</div><div class="font-black text-3xl leading-none"><span id="wishLeft">10</span>/10</div></div><button id="voiceBtn" onclick="toggleVoice()" class="w-12 h-12 bg-[#1e1e22] rounded-[10px] text-xl border border-zinc-800">🔊</button></div>
</div>

<div class="grid grid-cols-12 gap-3 mt-3 h-[calc(100vh-130px)]">
  <div class="col-span-12 lg:col-span-3 space-y-3 overflow-y-auto pr-1">
    <div class="hud rounded-[14px] p-4"><p class="mono text-[10px] text-zinc-500 tracking-widest">> MISSIONS BY SPARSH SINGHAL</p>
      <div class="mt-4 bg-black p-3.5 rounded-[10px] border-l-[3px] border-[#ff4d00]"><div class="flex justify-between mono text-[11px] font-bold"><span>ELIMINATE 3 DOUBTS</span><span id="q1t">0/3</span></div><div class="progress mt-2.5"><div id="q1b" style="width:0%"></div></div></div>
      <div class="mt-3 bg-black p-3.5 rounded-[10px] border-l-[3px] border-zinc-700"><div class="flex justify-between mono text-[11px] font-bold"><span>CODE KILL (1)</span><span id="q2t">0/1</span></div><div class="progress mt-2.5"><div id="q2b" style="width:0%"></div></div></div>
    </div>
    <div class="hud rounded-[14px] p-4"><p class="mono text-[10px] text-zinc-500 tracking-widest">> AMMO CRATE BY SPARSH SINGHAL 🪔</p><div id="lampRow" class="grid grid-cols-5 gap-2.5 mt-4"></div><button onclick="document.getElementById('payModal').classList.remove('hidden')" class="w-full mt-5 bg-gradient-to-r from-[#ff4d00] to-[#ff8a00] mono font-black py-3.5 rounded-[10px] shadow-[0_0_20px_rgba(255,77,0,0.4)]">RELOAD - ₹49 UNLIMITED</button></div>
    <div class="hud rounded-[14px] p-4"><p class="mono text-[10px] text-zinc-500 tracking-widest">> KILL LEADERS BY SPARSH SINGHAL 🏆</p><div id="board" class="mt-3 space-y-1.5 mono text-[11px]"></div></div>
  </div>

  <div class="col-span-12 lg:col-span-9 hud rounded-[16px] p-4 flex flex-col">
    <div id="chat" class="flex-1 overflow-y-auto space-y-5 pr-2"></div>
    <div class="flex gap-2.5 mt-4">
      <button onclick="quickAsk('Linked List ka code de with dry run')" class="mono text-[11px] bg-white text-black px-5 py-3 rounded-[10px] font-black">[E] CODE + DRY RUN</button>
      <button onclick="quickAsk('Ek tough topic ko action me samjha')" class="mono text-[11px] bg-[#1e1e22] border border-zinc-800 px-5 py-3 rounded-[10px] font-bold">[Q] CONCEPT RAID</button>
      <button onclick="quickAsk('Mera savage roast kar headshot de')" class="mono text-[11px] bg-[#1e1e22] border border-zinc-800 px-5 py-3 rounded-[10px] font-bold">[R] ROAST</button>
    </div>
    <div class="mt-4 bg-black border-2 border-[#2a2a2e] rounded-[12px] p-1.5 flex items-center gap-2 focus-within:border-[#ff4d00]/50 transition"><span class="mono text-xs px-3 text-[#ff4d00] font-black">></span><input id="q" class="flex-1 bg-transparent mono text-[15px] outline-none py-3.5 placeholder:text-zinc-600" placeholder="ENTER COMMAND BY SPARSH SINGHAL... (e.g. Recursion like gunfight)" onkeypress="if(event.key==='Enter')ask()"><button onclick="ask()" class="bg-[#ff4d00] hover:bg-[#ff5e1a] mono font-black w-20 h-12 rounded-[10px] shadow-[0_0_20px_rgba(255,77,0,0.5)]">FIRE 🔫</button></div>
  </div>
</div>
</div>

<div id="payModal" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4" style="background:rgba(0,0,0,0.95)">
  <div class="hud rounded-[24px] p-8 max-w-[420px] w-full text-center border-2 border-[#ff4d00]/50 shadow-[0_0_60px_rgba(255,77,0,0.3)]">
    <img src="/sparsh.jpg" class="w-28 h-28 rounded-[18px] mx-auto border-[4px] border-[#ff4d00] object-cover shadow-[0_0_30px_rgba(255,77,0,0.6)]">
    <h2 class="font-black text-3xl mt-5">OUT OF AMMO!</h2><p class="mono text-[12px] text-[#ff8a00] mt-1 font-bold">BY SPARSH SINGHAL</p>
    <div class="text-left mono text-[12px] mt-6 bg-black p-4 rounded-[12px] space-y-2 border border-zinc-800">
      <div>✓ UNLIMITED AMMO • NO ADS • GOD MODE</div><div>✓ 28 WEAPONS: PDF, IMAGE, CODE EXEC</div><div>✓ DRY RUN SCOPE + MINDMAP GRENADE</div><div>✓ SPARSH SINGHAL DIRECT RANK BOOST</div>
    </div>
    <div class="mono text-[11px] mt-5">OFFER EXPIRES: <span id="timer" class="text-[#ff4d00] font-black text-[13px]">23:59:59</span></div>
    <button onclick="buyPro()" class="w-full mt-5 bg-gradient-to-r from-[#ff4d00] to-[#ff8a00] mono font-black py-4 rounded-[12px] text-[14px] shadow-[0_0_30px_rgba(255,77,0,0.5)]">RELOAD UNLIMITED - ₹49/MO</button>
    <button onclick="closePay()" class="mono text-[11px] text-zinc-500 mt-4">CANCEL MISSION</button>
  </div>
</div>

<script>
let voiceOn=true, synth=window.speechSynthesis, queue=[], isSpeaking=false;
let audioCtx;
function playSound(freq,type,dur){try{if(!audioCtx)audioCtx=new(window.AudioContext||window.webkitAudioContext)(); let o=audioCtx.createOscillator(); let g=audioCtx.createGain(); o.frequency.value=freq; o.type=type; o.connect(g); g.connect(audioCtx.destination); g.gain.setValueAtTime(0.3, audioCtx.currentTime); g.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime+dur); o.start(); o.stop(audioCtx.currentTime+dur);}catch{}}
let userId=localStorage.getItem('genie_userId')||'user_'+Math.random().toString(36).substr(2,9); localStorage.setItem('genie_userId',userId);
let stats=JSON.parse(localStorage.getItem('genie_stats')||'{"xp":0,"level":1,"wishes":0,"q1":0,"q2":0}');
let isDev=localStorage.getItem('isDev')==='true';
function lamps(){let r=document.getElementById('lampRow'); r.innerHTML=''; for(let i=0;i<10;i++){let u=i<stats.wishes&&!isDev; r.innerHTML+=`<div class="ammo ${u?'used':''}">${u?'💨':'🪔'}</div>`;}}
function save(){localStorage.setItem('genie_stats',JSON.stringify(stats)); render();}
function render(){document.getElementById('wishLeft').innerText=isDev?'∞':10-stats.wishes; document.getElementById('lvlTop').innerText=stats.level; document.getElementById('xpBarTop').style.width=stats.xp+'%'; document.getElementById('xpText').innerText=stats.xp+'/100 XP'; document.getElementById('q1t').innerText=stats.q1+'/3'; document.getElementById('q1b').style.width=stats.q1/3*100+'%'; document.getElementById('q2t').innerText=stats.q2+'/1'; document.getElementById('q2b').style.width=stats.q2*100+'%'; lamps(); loadBoard();}
async function loadBoard(){try{let r=await fetch('/leaderboard?uid='+userId); let d=await r.json(); document.getElementById('rankTop').innerText=d.findIndex(u=>u.id===userId)+1||'-'; document.getElementById('board').innerHTML=d.slice(0,5).map((u,i)=>`<div class="flex justify-between p-2.5 bg-black rounded-[8px] border ${u.id===userId?'border-[#ff4d00]/50':'border-transparent'}"><span>${i==0?'👑':''} ${i+1}. ${u.name} ${u.id===userId?'[YOU]':''}</span><span class="text-[#ff4d00] font-bold">${u.xp}</span></div>`).join('');}catch{}}
let c=0;
document.getElementById('logo').addEventListener('click',()=>{
  playSound(800,'square',0.1); c++;
  if(c>=5){
    let pass = prompt("DEV ACCESS BY SPARSH SINGHAL - Enter Secret Code:");
    if(pass === "sparsh123"){
      isDev=!isDev; localStorage.setItem('isDev',isDev);
      playSound(isDev?1200:400,'sawtooth',0.4);
      alert(isDev?'GOD MODE ON - Welcome Founder Sparsh Singhal':'GOD MODE OFF');
      render();
    } else if(pass!== null) {
      alert("ACCESS DENIED! Only Sparsh Singhal can access.");
    }
    c=0;
  }
  setTimeout(()=>c=0,2000);
});
function toggleVoice(){voiceOn=!voiceOn; document.getElementById('voiceBtn').innerText=voiceOn?'🔊':'🔇'; if(!voiceOn){synth.cancel(); queue=[];}}
function speakQueue(t){if(!voiceOn) return; queue.push(...t.split(/(?<=[.!?])\\s+/)); if(!isSpeaking) playNext();}
function playNext(){if(!queue.length){isSpeaking=false; return;} isSpeaking=true; let u=new SpeechSynthesisUtterance(queue.shift()); u.lang='hi-IN'; u.rate=1.05; u.onend=()=>playNext(); synth.speak(u);}
function closePay(){document.getElementById('payModal').classList.add('hidden');}
function buyPro(){playSound(600,'sine',0.5); alert('₹49 - By Sparsh Singhal - Razorpay integration pending'); closePay();}
function quickAsk(t){document.getElementById('q').value=t; ask();}
async function ask(){
  let input=document.getElementById('q'); let q=input.value.trim(); if(!q) return;
  if(!isDev && stats.wishes>=10){document.getElementById('payModal').classList.remove('hidden'); playSound(150,'sawtooth',0.6); return;}
  playSound(900,'square',0.08); document.getElementById('main').classList.add('shake'); setTimeout(()=>document.getElementById('main').classList.remove('shake'),300);
  let chat=document.getElementById('chat'); chat.innerHTML+=`<div class="flex justify-end hitpop"><div class="bubble-user px-5 py-3 text-[14px] mono">${q}</div></div>`; input.value='';
  stats.wishes++; stats.q1=Math.min(3,stats.q1+1); if(/code|list|program/i.test(q)) stats.q2=1; stats.xp+=12; if(stats.xp>=100){stats.level++; stats.xp=0; playSound(1200,'sine',0.6); chat.innerHTML+=`<div class="text-center mono text-[#ff4d00] font-black text-[13px] py-3 animate-pulse">★★ LEVEL UP BY SPARSH SINGHAL - LVL ${stats.level} - NEW WEAPON UNLOCKED ★★</div>`;} save();
  fetch('/update_xp',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({uid:userId, xp:(stats.level-1)*100+stats.xp})});
  chat.innerHTML+=`<div id="typing" class="flex gap-3"><img src="/sparsh.jpg" class="w-12 h-12 rounded-[10px] border-2 border-[#ff4d00] object-cover"><div class="bubble-ai p-4 mono text-[12px] text-zinc-400 animate-pulse">> SPARSH SINGHAL'S GENIE AIMING... LOCKING TARGET...</div></div>`; chat.scrollTop=chat.scrollHeight;
  let res=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({q})}); let data=await res.json();
  document.getElementById('typing')?.remove(); playSound(500,'sine',0.2);
  chat.innerHTML+=`<div class="flex gap-3 hitpop"><img src="/sparsh.jpg" class="w-12 h-12 rounded-[10px] border-2 border-[#ff4d00] object-cover shadow-[0_0_15px_rgba(255,77,0,0.5)]"><div class="bubble-ai p-4 max-w-[78%] text-[14px] leading-relaxed whitespace-pre-wrap">${data.ans}<div class="mt-3 flex items-center gap-2 mono text-[10px] text-zinc-500"><span class="bg-[#ff4d00] text-white px-2 py-0.5 rounded-[4px]">BY SPARSH SINGHAL</span><span>HIT CONFIRMED +12 XP // ENEMY DOWN ✓</span></div></div></div>`; chat.scrollTop=chat.scrollHeight; speakQueue(data.ans);
}
let sec=86399; setInterval(()=>{sec--; let h=Math.floor(sec/3600), m=Math.floor((sec%3600)/60), s=sec%60; document.getElementById('timer').innerText=`${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;},1000);
document.getElementById('chat').innerHTML=`<div class="flex gap-3 hitpop"><img src="/sparsh.jpg" class="w-12 h-12 rounded-[10px] border-2 border-[#ff4d00] object-cover"><div class="bubble-ai p-5 max-w-[78%] text-[15px] leading-relaxed">WELCOME TO BATTLEFIELD, AAKA. I AM SPARSH SINGHAL'S GENIE.<br><br>🔫 Har doubt ek enemy hai. Har answer pe +12 XP, Shield badhega.<br>🪔 Ammo 10 ke baad khatam — Pro leke unlimited reload kar by Sparsh Singhal.<br><br><span class="mono text-[11px] text-zinc-500">TIP: FIRE dabate hi screen shake + hit sound ayega. 5x logo click = GOD MODE (Password Protected).</span></div></div>`; render();
</script></body></html>
"""

@app.route("/")
def home(): return render_template_string(HTML_PAGE)
@app.route("/sparsh.jpg")
def photo():
    try: return send_from_directory(".", "sparsh.jpg")
    except: return "", 204
@app.route("/leaderboard")
def leaderboard(): return jsonify(sorted(REAL_LEADERBOARD.values(), key=lambda x: x['xp'], reverse=True)[:10])
@app.route("/update_xp", methods=["POST"])
def update_xp():
    d=request.json; uid=d.get("uid")
    REAL_LEADERBOARD[uid]={"id":uid,"name":f"Grinder {uid[-3:].upper()}","xp":d.get("xp",0)}
    return jsonify({"ok":True})
@app.route("/ask", methods=["POST"])
def ask_gemini():
    q=request.json.get("q","")
    if not client: return jsonify({"ans":"API Key missing! Vercel me GOOGLE_API_KEY set karo."})
    try:
        resp=client.models.generate_content(model="gemini-3.6-flash", contents=f"You are StudyGenie by Sparsh Singhal, created by Sparsh Singhal. Gen-Z Hinglish, savage, funny, max 180 words. Always say you are made by Sparsh Singhal. User: {q}")
        return jsonify({"ans":resp.text})
    except Exception as e: return jsonify({"ans":f"Error {e}"})
if __name__=="__main__": app.run()
