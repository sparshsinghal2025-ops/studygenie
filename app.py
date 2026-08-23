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
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@800&family=Outfit:wght@700;900&display=swap" rel="stylesheet">
<style>
body{background:#050507!important; color:#fff}
.mono{font-family:'JetBrains Mono',monospace}
.hud{background:#111113; border:1px solid #232326}
.bubble-user{background:#fff; color:#000; border-radius:12px 12px 2px 12px; font-weight:800}
.bubble-ai{background:#1a1a1e; border-left:4px solid #ff4d00; border-radius:2px 14px 14px 14px}
.ammo{width:38px; height:48px; background:#1c1c20; border:1px solid #2c2c30; display:flex; align-items:center; justify-content:center; font-size:18px}
.ammo.used{opacity:0.15}
.progress{height:10px; background:#1a1a1e; border:1px solid #2a2a2e; transform:skew(-10deg)}
.progress>div{height:100%; background:#ff4d00}
</style>
</head>
<body class="p-3">
<div class="max-w-[1400px] mx-auto hud rounded-[14px] px-5 py-3 flex justify-between items-center">
  <div class="flex items-center gap-5">
    <img id="logo" src="/sparsh.jpg" class="w-20 h-20 rounded-[12px] border-[3px] border-[#ff4d00] object-cover shadow-[0_0_30px_rgba(255,77,0,0.6)] cursor-pointer">
    <div><h1 class="font-black text-[20px] tracking-widest">STUDYGENIE <span class="text-[#ff4d00]">: BATTLE</span></h1><p class="mono text-[11px] text-zinc-400">LVL <span id="lvlTop">1</span> // RANK #<span id="rankTop">?</span> // BY SPARSH SINGHAL</p><div class="flex items-center gap-2 mt-1.5"><span class="mono text-[9px]">SHIELD</span><div class="w-32 progress"><div id="xpBarTop" style="width:0%"></div></div><span id="xpText" class="mono text-[10px]">0/100 XP</span></div></div>
  </div>
  <div class="flex items-center gap-4"><div class="mono text-right"><div class="text-[10px] text-zinc-500">AMMO</div><div class="font-black text-2xl leading-none"><span id="wishLeft">10</span>/10</div></div><button id="voiceBtn" onclick="toggleVoice()" class="w-10 h-10 bg-[#1e1e22] rounded-[8px]">🔊</button></div>
</div>

<div class="max-w-[1400px] mx-auto grid grid-cols-12 gap-3 mt-3 h-[calc(100vh-90px)]">
  <div class="col-span-12 lg:col-span-3 space-y-3">
    <div class="hud rounded-[12px] p-4"><p class="mono text-[10px] text-zinc-500">> MISSIONS BY SPARSH SINGHAL</p>
      <div class="mt-3 bg-black p-3 rounded-[8px] border-l-2 border-[#ff4d00]"><div class="flex justify-between mono text-[11px]"><span>ELIMINATE 3 DOUBTS</span><span id="q1t">0/3</span></div><div class="progress mt-2"><div id="q1b" style="width:0%"></div></div></div>
      <div class="mt-2 bg-black p-3 rounded-[8px] border-l-2 border-zinc-700"><div class="flex justify-between mono text-[11px]"><span>CODE KILL (1)</span><span id="q2t">0/1</span></div><div class="progress mt-2"><div id="q2b" style="width:0%"></div></div></div>
    </div>
    <div class="hud rounded-[12px] p-4"><p class="mono text-[10px] text-zinc-500">> AMMO CRATE BY SPARSH SINGHAL 🪔</p><div id="lampRow" class="grid grid-cols-5 gap-2 mt-3"></div><button onclick="document.getElementById('payModal').classList.remove('hidden')" class="w-full mt-4 bg-[#ff4d00] mono font-black py-3 rounded-[8px]">RELOAD - ₹49 UNLIMITED</button></div>
    <div class="hud rounded-[12px] p-4"><p class="mono text-[10px] text-zinc-500">> KILL LEADERS BY SPARSH SINGHAL 🏆</p><div id="board" class="mt-3 space-y-1 mono text-[11px]"></div></div>
  </div>

  <div class="col-span-12 lg:col-span-9 hud rounded-[14px] p-4 flex flex-col">
    <div id="chat" class="flex-1 overflow-y-auto space-y-4"></div>
    <div class="flex gap-2 mt-4">
      <button onclick="quickAsk('Linked List ka code de with dry run')" class="mono text-[11px] bg-white text-black px-4 py-2.5 rounded-[8px] font-black">[E] CODE + DRY RUN</button>
      <button onclick="quickAsk('Ek tough topic ko action me samjha')" class="mono text-[11px] bg-[#1e1e22] px-4 py-2.5 rounded-[8px]">[Q] CONCEPT RAID</button>
      <button onclick="quickAsk('Mera savage roast kar')" class="mono text-[11px] bg-[#1e1e22] px-4 py-2.5 rounded-[8px]">[R] ROAST</button>
    </div>
    <div class="mt-4 bg-black border border-[#2a2a2e] rounded-[10px] p-1.5 flex items-center gap-2"><span class="mono text-xs px-2 text-zinc-600">></span><input id="q" class="flex-1 bg-transparent mono text-[14px] outline-none py-3" placeholder="ENTER COMMAND BY SPARSH SINGHAL..." onkeypress="if(event.key==='Enter')ask()"><button onclick="ask()" class="bg-[#ff4d00] mono font-black w-16 h-11 rounded-[8px]">FIRE</button></div>
  </div>
</div>

<div id="payModal" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4" style="background:rgba(0,0,0,0.92)">
  <div class="hud rounded-[20px] p-6 max-w-[400px] w-full text-center border border-[#ff4d00]/50">
    <img src="/sparsh.jpg" class="w-24 h-24 rounded-[14px] mx-auto border-[3px] border-[#ff4d00] object-cover">
    <h2 class="font-black text-2xl mt-4">OUT OF AMMO!</h2><p class="mono text-[11px] text-zinc-400 mt-1">BY SPARSH SINGHAL</p>
    <div class="text-left mono text-[11px] mt-4 bg-black p-3 rounded-[10px] space-y-1.5 border border-zinc-800">
      <div>> UNLIMITED AMMO • NO ADS</div><div>> 28 WEAPONS: PDF, IMAGE, CODE EXEC</div><div>> DRY RUN SCOPE, MINDMAP, MOCK TEST</div><div>> SPARSH SINGHAL DIRECT SUPPORT</div>
    </div>
    <div class="mono text-[10px] mt-4">OFFER EXPIRES: <span id="timer" class="text-[#ff4d00] font-bold">23:59:59</span></div>
    <button onclick="buyPro()" class="w-full mt-4 bg-[#ff4d00] mono font-black py-3.5 rounded-[10px]">RELOAD UNLIMITED - ₹49/MO</button>
    <button onclick="closePay()" class="mono text-[10px] text-zinc-500 mt-3">CANCEL MISSION</button>
  </div>
</div>

<script>
let voiceOn=true, synth=window.speechSynthesis, queue=[], isSpeaking=false;
let userId=localStorage.getItem('genie_userId')||'user_'+Math.random().toString(36).substr(2,9); localStorage.setItem('genie_userId',userId);
let stats=JSON.parse(localStorage.getItem('genie_stats')||'{"xp":0,"level":1,"wishes":0,"q1":0,"q2":0}');
let isDev=localStorage.getItem('isDev')==='true';
function lamps(){let r=document.getElementById('lampRow'); r.innerHTML=''; for(let i=0;i<10;i++){let u=i<stats.wishes&&!isDev; r.innerHTML+=`<div class="ammo ${u?'used':''}">${u?'💨':'🪔'}</div>`;}}
function save(){localStorage.setItem('genie_stats',JSON.stringify(stats)); render();}
function render(){document.getElementById('wishLeft').innerText=isDev?'∞':10-stats.wishes; document.getElementById('lvlTop').innerText=stats.level; document.getElementById('xpBarTop').style.width=stats.xp+'%'; document.getElementById('xpText').innerText=stats.xp+'/100 XP'; document.getElementById('q1t').innerText=stats.q1+'/3'; document.getElementById('q1b').style.width=stats.q1/3*100+'%'; document.getElementById('q2t').innerText=stats.q2+'/1'; document.getElementById('q2b').style.width=stats.q2*100+'%'; lamps(); loadBoard();}
async function loadBoard(){try{let r=await fetch('/leaderboard?uid='+userId); let d=await r.json(); document.getElementById('rankTop').innerText=d.findIndex(u=>u.id===userId)+1||'-'; document.getElementById('board').innerHTML=d.slice(0,5).map((u,i)=>`<div class="flex justify-between p-2 bg-black rounded-[6px] ${u.id===userId?'border border-[#ff4d00]/40':''}"><span>${i+1}. ${u.name} ${u.id===userId?'[YOU]':''}</span><span>${u.xp}</span></div>`).join('');}catch{}}
let c=0; document.getElementById('logo').addEventListener('click',()=>{c++; if(c>=5){isDev=!isDev; localStorage.setItem('isDev',isDev); alert(isDev?'GOD MODE ON - Sparsh Singhal':'OFF'); render(); c=0;} setTimeout(()=>c=0,2000);});
function toggleVoice(){voiceOn=!voiceOn; document.getElementById('voiceBtn').innerText=voiceOn?'🔊':'🔇'; if(!voiceOn){synth.cancel(); queue=[];}}
function speakQueue(t){if(!voiceOn) return; queue.push(...t.split(/(?<=[.!?])\\s+/)); if(!isSpeaking) playNext();}
function playNext(){if(!queue.length){isSpeaking=false; return;} isSpeaking=true; let u=new SpeechSynthesisUtterance(queue.shift()); u.lang='hi-IN'; u.rate=1.05; u.onend=()=>playNext(); synth.speak(u);}
function closePay(){document.getElementById('payModal').classList.add('hidden');}
function buyPro(){alert('₹49 - By Sparsh Singhal'); closePay();}
function quickAsk(t){document.getElementById('q').value=t; ask();}
async function ask(){
  let input=document.getElementById('q'); let q=input.value.trim(); if(!q) return;
  if(!isDev && stats.wishes>=10){document.getElementById('payModal').classList.remove('hidden'); return;}
  let chat=document.getElementById('chat'); chat.innerHTML+=`<div class="flex justify-end"><div class="bubble-user px-4 py-2.5 text-[13px] mono">${q}</div></div>`; input.value='';
  stats.wishes++; stats.q1=Math.min(3,stats.q1+1); if(/code|list|program/i.test(q)) stats.q2=1; stats.xp+=12; if(stats.xp>=100){stats.level++; stats.xp=0; chat.innerHTML+=`<div class="text-center mono text-[#ff4d00] text-xs py-2">>> LEVEL UP BY SPARSH SINGHAL - LVL ${stats.level} <<</div>`;} save();
  fetch('/update_xp',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({uid:userId, xp:(stats.level-1)*100+stats.xp})});
  chat.innerHTML+=`<div id="typing" class="mono text-[11px] opacity-40">> SPARSH SINGHAL'S GENIE AIMING...</div>`; chat.scrollTop=chat.scrollHeight;
  let res=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({q})}); let data=await res.json();
  document.getElementById('typing')?.remove();
  chat.innerHTML+=`<div class="flex gap-3"><img src="/sparsh.jpg" class="w-8 h-8 rounded-[6px] border border-[#ff4d00] object-cover"><div class="bubble-ai p-3.5 max-w-[80%] text-[13.5px] whitespace-pre-wrap">${data.ans}<div class="mt-2 mono text-[9px] text-zinc-500">BY SPARSH SINGHAL • +12 XP</div></div></div>`; chat.scrollTop=chat.scrollHeight; speakQueue(data.ans);
}
let sec=86399; setInterval(()=>{sec--; let h=Math.floor(sec/3600), m=Math.floor((sec%3600)/60), s=sec%60; document.getElementById('timer').innerText=`${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;},1000);
document.getElementById('chat').innerHTML=`<div class="flex gap-3"><img src="/sparsh.jpg" class="w-10 h-10 rounded-[8px] border-2 border-[#ff4d00] object-cover"><div class="bubble-ai p-4 max-w-[80%] text-[14px]">WELCOME TO BATTLEFIELD, AAKA. I AM SPARSH SINGHAL'S GENIE.<br><br>Har doubt ek enemy hai. Har answer pe +12 XP.<br>Ammo 10 ke baad khatam — Pro leke unlimited reload kar by Sparsh Singhal.</div></div>`; render();
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
    if not client: return jsonify({"ans":"API Key missing!"})
    try:
        resp=client.models.generate_content(model="gemini-3.6-flash", contents=f"You are StudyGenie by Sparsh Singhal, created by Sparsh Singhal. Gen-Z Hinglish. Max 180 words. User: {q}")
        return jsonify({"ans":resp.text})
    except Exception as e: return jsonify({"ans":f"Error {e}"})
if __name__=="__main__": app.run()
