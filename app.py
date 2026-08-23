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
<title>StudyGenie by Sparsh Singhal - Battle Mode</title>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@700&family=Outfit:wght@700;900&display=swap" rel="stylesheet">
<style>
*{font-family:'Outfit',sans-serif}
body{background:#09090b!important; color:#fff; overflow:hidden}
.mono{font-family:'JetBrains Mono',monospace}
.hud{background:rgba(20,20,22,0.9); border:1px solid #27272a; backdrop-filter:blur(12px)}
.bubble-user{background:#fff; color:#000; border-radius:12px 12px 2px 12px; font-weight:700; clip-path: polygon(0 0, 100% 0, 100% 85%, 92% 100%, 0 100%)}
.bubble-ai{background:#18181b; border-left:3px solid #ff4d00; border-radius:2px 12px 12px 12px}
.ammo{width:32px; height:44px; background:#1f1f22; border:1px solid #2a2a2e; clip-path: polygon(20% 0, 100% 0, 100% 100%, 0 100%, 0 20%); display:flex; align-items:center; justify-content:center; transition:0.2s}
.ammo.used{opacity:0.15; transform:translateY(4px)}
.progress{height:8px; background:#18181b; border:1px solid #27272a; transform:skew(-12deg)}
.progress>div{height:100%; background:linear-gradient(90deg,#ff4d00,#ff8a00)}
</style>
</head>
<body class="p-2">
<div class="max-w-[1400px] mx-auto hud rounded-[12px] px-4 py-2.5 flex justify-between items-center">
  <div class="flex items-center gap-4">
    <img id="logo" src="/sparsh.jpg" class="w-16 h-16 rounded-[8px] border-[3px] border-[#ff4d00] object-cover shadow-[0_0_20px_rgba(255,77,0,0.5)]">
    <div><h1 class="font-black text-[18px] tracking-widest">STUDYGENIE <span class="text-[#ff4d00]">: BATTLE</span></h1><p class="mono text-[11px] opacity-70">LVL <span id="lvlTop">1</span> // RANK #<span id="rankTop">?</span> // BY SPARSH SINGHAL</p></div>
    <div class="hidden md:flex items-center gap-2 ml-6"><div class="mono text-[10px]">SHIELD</div><div class="w-28 progress"><div id="xpBarTop" style="width:10%"></div></div><div class="mono text-[10px]" id="xpText">12/100 XP</div></div>
  </div>
  <div class="flex items-center gap-3"><div class="mono text-right"><div class="text-[10px] opacity-50">AMMO</div><div class="font-black text-lg leading-none"><span id="wishLeft">10</span>/10</div></div><button id="voiceBtn" onclick="toggleVoice()" class="w-9 h-9 bg-[#222] rounded-[6px]">🔊</button></div>
</div>

<div class="max-w-[1400px] mx-auto grid grid-cols-12 gap-2 mt-2 h-[calc(100vh-68px)]">
  <div class="col-span-12 lg:col-span-3 space-y-2 overflow-y-auto">
    <div class="hud rounded-[10px] p-3"><p class="mono text-[10px] opacity-50">> MISSIONS BY SPARSH SINGHAL</p>
      <div class="mt-3 bg-[#101012] p-2.5 rounded-[6px] border-l-2 border-[#ff4d00]"><div class="flex justify-between mono text-[11px]"><span>ELIMINATE 3 DOUBTS</span><span id="q1t">0/3</span></div><div class="progress mt-2"><div id="q1b" style="width:0%"></div></div></div>
      <div class="mt-2 bg-[#101012] p-2.5 rounded-[6px] border-l-2 border-zinc-600"><div class="flex justify-between mono text-[11px]"><span>CODE KILL (1)</span><span id="q2t">0/1</span></div><div class="progress mt-2"><div id="q2b" style="width:0%"></div></div></div>
    </div>
    <div class="hud rounded-[10px] p-3"><p class="mono text-[10px] opacity-50">> AMMO CRATE 🪔</p><div id="lampRow" class="grid grid-cols-5 gap-1.5 mt-3"></div><button onclick="document.getElementById('payModal').classList.remove('hidden')" class="w-full mt-3 mono text-[11px] bg-[#ff4d00] py-2 rounded-[6px] font-bold">RELOAD - ₹49 UNLIMITED</button></div>
    <div class="hud rounded-[10px] p-3"><p class="mono text-[10px] opacity-50">> KILL LEADERS BY SPARSH SINGHAL 🏆</p><div id="board" class="mt-2 space-y-1 mono text-[11px]"></div></div>
  </div>

  <div class="col-span-12 lg:col-span-9 hud rounded-[12px] p-3 flex flex-col h-full">
    <div class="flex-1 overflow-y-auto space-y-3 pr-1" id="chat"></div>
    <div class="flex gap-2 mt-3">
      <button onclick="quickAsk('Linked List ka code de with dry run - enemy down karna hai')" class="mono text-[10px] bg-white text-black px-3 py-2 rounded-[6px] font-bold">[E] CODE + DRY RUN</button>
      <button onclick="quickAsk('Ek tough topic ko action me samjha')" class="mono text-[10px] bg-[#222] px-3 py-2 rounded-[6px]">[Q] CONCEPT RAID</button>
      <button onclick="quickAsk('Mera savage roast kar - headshot de')" class="mono text-[10px] bg-[#222] px-3 py-2 rounded-[6px]">[R] ROAST</button>
    </div>
    <div class="mt-3 bg-black border border-[#2a2a2a] rounded-[8px] p-1 flex items-center gap-2"><span class="mono text-[10px] px-2 opacity-40">></span><input id="q" class="flex-1 bg-transparent mono text-[13px] outline-none py-2.5" placeholder="ENTER COMMAND... (eg. Explain Recursion like a gunfight)" onkeypress="if(event.key==='Enter')ask()"><button onclick="ask()" class="bg-[#ff4d00] mono font-black w-12 h-10 rounded-[6px]">FIRE</button></div>
  </div>
</div>

<div id="payModal" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4" style="background:rgba(0,0,0,0.9)">
  <div class="hud rounded-[16px] p-6 max-w-[380px] w-full text-center border border-[#ff4d00]/40">
    <img src="/sparsh.jpg" class="w-20 h-20 rounded-[12px] mx-auto border-2 border-[#ff4d00] object-cover">
    <h2 class="font-black text-xl mt-3">OUT OF AMMO!</h2><p class="mono text-[11px] opacity-60 mt-1">BY SPARSH SINGHAL • RELOAD REQUIRED</p>
    <div class="text-left mono text-[11px] mt-4 bg-black p-3 rounded-[8px] space-y-1 border border-zinc-800">
      <div>> UNLIMITED AMMO • NO ADS • FAST RELOAD</div><div>> 28 WEAPONS: PDF SCAN, IMAGE SCAN, CODE EXEC</div><div>> DRY RUN SCOPE, MINDMAP GRENADE, MOCK TEST</div><div>> + RANK BOOST + SPARSH SINGHAL DIRECT SUPPORT</div>
    </div>
    <div class="mono text-[10px] mt-3">OFFER EXPIRES: <span id="timer" class="text-[#ff4d00] font-bold">23:59:59</span></div>
    <button onclick="buyPro()" class="w-full mt-4 bg-[#ff4d00] mono font-black py-3 rounded-[6px]">RELOAD UNLIMITED - ₹49/MO</button>
    <button onclick="closePay()" class="mono text-[10px] opacity-40 mt-2">CANCEL MISSION</button>
  </div>
</div>

<script>
let voiceOn=true, synth=window.speechSynthesis, queue=[], isSpeaking=false;
let userId=localStorage.getItem('genie_userId')||'user_'+Math.random().toString(36).substr(2,9); localStorage.setItem('genie_userId',userId);
let stats=JSON.parse(localStorage.getItem('genie_stats')||'{"xp":0,"level":1,"wishes":0,"q1":0,"q2":0}');
let isDev=localStorage.getItem('isDev')==='true';
function lamps(){let r=document.getElementById('lampRow'); r.innerHTML=''; for(let i=0;i<10;i++){let u=i<stats.wishes&&!isDev; r.innerHTML+=`<div class="ammo ${u?'used':''}">${u?'·':'🪔'}</div>`;}}
function save(){localStorage.setItem('genie_stats',JSON.stringify(stats)); render();}
function render(){document.getElementById('wishLeft').innerText=isDev?'∞':10-stats.wishes; document.getElementById('lvlTop').innerText=stats.level; document.getElementById('xpBarTop').style.width=stats.xp+'%'; document.getElementById('xpText').innerText=stats.xp+'/100 XP'; document.getElementById('q1t').innerText=stats.q1+'/3'; document.getElementById('q1b').style.width=stats.q1/3*100+'%'; document.getElementById('q2t').innerText=stats.q2+'/1'; document.getElementById('q2b').style.width=stats.q2*100+'%'; lamps(); loadBoard();}
async function loadBoard(){try{let r=await fetch('/leaderboard?uid='+userId); let d=await r.json(); document.getElementById('rankTop').innerText=d.findIndex(u=>u.id===userId)+1||'-'; document.getElementById('board').innerHTML=d.slice(0,5).map((u,i)=>`<div class="flex justify-between p-1.5 bg-[#101012] ${u.id===userId?'border border-[#ff4d00]/30':''}"><span>${i==0?'#1':'#'+(i+1)} ${u.name} ${u.id===userId?'[YOU]':''}</span><span>${u.xp} KILLS</span></div>`).join('');}catch{}}
let c=0; document.getElementById('logo').addEventListener('click',()=>{c++; if(c>=5){isDev=!isDev; localStorage.setItem('isDev',isDev); alert(isDev?'DEV MODE: GOD MODE ON - Sparsh Singhal':'GOD MODE OFF'); render(); c=0;} setTimeout(()=>c=0,2000);});
function toggleVoice(){voiceOn=!voiceOn; document.getElementById('voiceBtn').innerText=voiceOn?'🔊':'🔇'; if(!voiceOn){synth.cancel(); queue=[];}}
function speakQueue(t){if(!voiceOn) return; queue.push(...t.split(/(?<=[.!?])\\s+/)); if(!isSpeaking) playNext();}
function playNext(){if(!queue.length){isSpeaking=false; return;} isSpeaking=true; let u=new SpeechSynthesisUtterance(queue.shift()); u.lang='hi-IN'; u.rate=1.05; u.onend=()=>playNext(); synth.speak(u);}
function closePay(){document.getElementById('payModal').classList.add('hidden');}
function buyPro(){alert('₹49 Reload by Sparsh Singhal - Razorpay yahan lagega'); closePay();}
function quickAsk(t){document.getElementById('q').value=t; ask();}
async function ask(){
  let input=document.getElementById('q'); let q=input.value.trim(); if(!q) return;
  if(!isDev && stats.wishes>=10){document.getElementById('payModal').classList.remove('hidden'); return;}
  let chat=document.getElementById('chat'); chat.innerHTML+=`<div class="flex justify-end"><div class="bubble-user px-4 py-2 text-[13px] mono">${q}</div></div>`; input.value='';
  stats.wishes++; stats.q1=Math.min(3,stats.q1+1); if(/code|list|program/i.test(q)) stats.q2=1; stats.xp+=12; if(stats.xp>=100){stats.level++; stats.xp=0; chat.innerHTML+=`<div class="text-center mono text-[#ff4d00] text-xs py-2">>> LEVEL UP! LVL ${stats.level} BY SPARSH SINGHAL // NEW WEAPON UNLOCKED <<</div>`;} save();
  fetch('/update_xp',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({uid:userId, xp:(stats.level-1)*100+stats.xp})});
  chat.innerHTML+=`<div id="typing" class="mono text-[11px] opacity-40">> GENIE AIMING...</div>`; chat.scrollTop=chat.scrollHeight;
  let res=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({q})}); let data=await res.json();
  document.getElementById('typing')?.remove();
  chat.innerHTML+=`<div class="flex gap-2"><div class="w-7 h-7 bg-[#ff4d00] rounded-[4px] flex items-center justify-center text-xs">🧞</div><div class="bubble-ai p-3 max-w-[85%] text-[13px] whitespace-pre-wrap"><span>${data.ans}</span><div class="mt-2 mono text-[9px] opacity-40">BY SPARSH SINGHAL • HIT CONFIRMED +12 XP // ENEMY DOWN</div></div></div>`; chat.scrollTop=chat.scrollHeight; speakQueue(data.ans);
}
let sec=86399; setInterval(()=>{sec--; let h=Math.floor(sec/3600), m=Math.floor((sec%3600)/60), s=sec%60; document.getElementById('timer').innerText=`${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;},1000);
document.getElementById('chat').innerHTML=`<div class="flex gap-2"><div class="w-7 h-7 bg-[#ff4d00] rounded-[4px] flex items-center justify-center">🧞</div><div class="bubble-ai p-4 max-w-[85%] text-[13px]">WELCOME TO BATTLEFIELD, AAKA. I AM SPARSH SINGHAL'S GENIE.<br><br>Har doubt ek enemy hai. Har answer pe +12 XP, Shield badhega.<br>Ammo 10 ke baad khatam — Pro leke unlimited reload kar.</div></div>`; render();
</script></body></html>
"""

@app.route("/")
def home(): return render_template_string(HTML_PAGE)

@app.route("/sparsh.jpg")
def photo():
    try: return send_from_directory(".", "sparsh.jpg")
    except: return "", 204

@app.route("/leaderboard")
def leaderboard():
    return jsonify(sorted(REAL_LEADERBOARD.values(), key=lambda x: x['xp'], reverse=True)[:10])

@app.route("/update_xp", methods=["POST"])
def update_xp():
    d=request.json; uid=d.get("uid")
    REAL_LEADERBOARD[uid]={"id":uid,"name":f"Grinder {uid[-3:].upper()}","xp":d.get("xp",0),"level":1}
    return jsonify({"ok":True})

@app.route("/ask", methods=["POST"])
def ask_gemini():
    q=request.json.get("q","")
    if not client: return jsonify({"ans":"API Key missing! Vercel me GOOGLE_API_KEY set karo."})
    try:
        resp=client.models.generate_content(model="gemini-3.6-flash", contents=f"You are StudyGenie by Sparsh Singhal, created by Sparsh Singhal. Gen-Z Hinglish Genie, funny, max 180 words. Always mention you are made by Sparsh Singhal if asked. User: {q}")
        return jsonify({"ans":resp.text})
    except Exception as e: return jsonify({"ans":f"Error {e}"})

if __name__=="__main__": app.run()
