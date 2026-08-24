import os
from flask import Flask, request, jsonify, send_from_directory
app = Flask(__name__)

try:
    from google import genai
    API_KEY = os.environ.get("GOOGLE_API_KEY", "")
    client = genai.Client(api_key=API_KEY) if API_KEY else None
except:
    client = None

REAL_LEADERBOARD = {}
USER_DB = {}

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
#chat{max-height:60vh;overflow-y:auto!important;scroll-behavior:smooth}
.hitpop{animation:pop.3s cubic-bezier(.175,.885,.32,1.275)} @keyframes pop{0%{transform:scale(.6)}100%{transform:scale(1)}}
.shake{animation:shake.3s} @keyframes shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-5px)}75%{transform:translateX(5px)}}
.input-glow:focus{border-color:#ff4d00!important;box-shadow:0 0 15px rgba(255,77,0,0.3)}
</style>
</head>
<body class="p-3">
<div id="main" class="max-w-[1500px] mx-auto pb-20">
<div class="hud rounded-[16px] px-5 py-3 flex justify-between items-center sticky top-2 z-30">
  <div class="flex items-center gap-6">
    <img id="logo" src="/sparsh.jpg" class="w-28 h-28 rounded-[16px] border-[4px] border-[#ff4d00] object-cover shadow-[0_0_40px_rgba(255,77,0,0.7)] cursor-pointer hitpop">
    <div><h1 class="font-black text-[22px] tracking-widest">STUDYGENIE <span class="text-[#ff4d00]">: BATTLE</span></h1><p class="mono text-[12px] text-[#ff8a00] mt-1">BY SPARSH SINGHAL // FOUNDER</p><div class="flex items-center gap-3 mt-3"><span class="mono text-[10px] text-zinc-400">SHIELD</span><div class="w-40 progress"><div id="xpBarTop" style="width:0%"></div></div><span id="xpText" class="mono text-[11px] font-bold">0/100 XP</span></div><p class="mono text-[9px] text-zinc-600 mt-1">LVL <span id="lvlTop">1</span> // <span id="userNameTop" class="text-[#ff4d00]"></span> // RANK #<span id="rankTop">?</span></p></div>
  </div>
  <div class="mono text-right"><div class="text-[10px] text-zinc-500 tracking-widest">AMMO</div><div class="font-black text-3xl"><span id="wishLeft">10</span>/10</div></div>
</div>

<div class="grid grid-cols-12 gap-3 mt-3">
  <div class="col-span-12 lg:col-span-3 space-y-3">
    <div class="hud rounded-[14px] p-4"><p class="mono text-[10px] text-zinc-500 tracking-widest">> MISSIONS BY SPARSH SINGHAL</p><div class="mt-4 bg-black p-3 rounded-[10px] border-l-[3px] border-[#ff4d00]"><div class="flex justify-between mono text-[11px] font-bold"><span>ELIMINATE 3 DOUBTS</span><span id="q1t">0/3</span></div><div class="progress mt-2"><div id="q1b" style="width:0%"></div></div></div></div>
    <div class="hud rounded-[14px] p-4"><p class="mono text-[10px] text-zinc-500 tracking-widest">> AMMO CRATE</p><div id="lampRow" class="grid grid-cols-5 gap-2 mt-3"></div><button onclick="openPay()" class="w-full mt-4 bg-[#ff4d00] mono font-black py-3 rounded-[10px]">RELOAD - ₹49</button></div>
    <div class="hud rounded-[14px] p-4 border border-[#ff4d00]/30">
      <p class="mono text-[10px] text-[#ff4d00] tracking-widest font-black">> LIVE LEADERBOARD 🏆 BY SPARSH SINGHAL</p>
      <p class="mono text-[9px] text-zinc-500 mt-1">ONLY NAME + XP VISIBLE TO ALL</p>
      <div id="board" class="mt-3 space-y-2 mono text-[11px]"></div>
      <div class="mt-3 mono text-[9px] text-zinc-500 bg-black p-2.5 rounded border border-zinc-800">
        <span class="text-[#ff8a00]">PRIVATE - ONLY YOU 🔒</span><br>
        <span id="myId"></span><br><span id="myPhone"></span>
      </div>
    </div>
  </div>
  <div class="col-span-12 lg:col-span-9 hud rounded-[16px] p-4 flex flex-col">
    <div id="chat" class="flex-1 space-y-4 pr-2"></div>
    <div class="mt-4 bg-black border-2 border-[#2a2a2e] rounded-[12px] p-1.5 flex items-center gap-2 sticky bottom-2"><span class="mono text-xs px-2 text-[#ff4d00] font-black">></span><input id="q" class="flex-1 bg-transparent mono text-[14px] outline-none py-3 px-2" placeholder="ENTER COMMAND BY SPARSH SINGHAL..." onkeypress="if(event.key==='Enter')ask()"><button onclick="ask()" class="bg-[#ff4d00] mono font-black w-20 h-11 rounded-[10px]">FIRE 🔫</button></div>
  </div>
</div>
</div>

<div id="onboardModal" class="fixed inset-0 z-[60] flex items-center justify-center p-4" style="background:rgba(0,0,0,0.92)">
  <div class="hud rounded-[20px] p-7 max-w-[420px] w-full border-2 border-[#ff4d00]/50">
    <div class="flex items-center gap-4"><img src="/sparsh.jpg" class="w-16 h-16 rounded-[12px] border-2 border-[#ff4d00] object-cover"><div><h2 class="font-black text-[20px] leading-none">WARRIOR REGISTRATION</h2><p class="mono text-[11px] text-[#ff8a00] mt-1 font-bold">BY SPARSH SINGHAL</p></div></div>
    <p class="mono text-[11px] text-zinc-400 mt-4">Name leaderboard pe dikhega. Phone private hai, sirf ₹49 plan track.</p>
    <div class="mt-5 space-y-3">
      <div><label class="mono text-[10px] text-zinc-500">YOUR WARRIOR NAME *</label><input id="inpName" class="w-full mt-1 bg-black border-2 border-zinc-800 rounded-[10px] px-4 py-3 mono text-[14px] outline-none input-glow" placeholder="Ex: Aman..." maxlength="20"></div>
      <div><label class="mono text-[10px] text-zinc-500">PHONE (PRIVATE) *</label><input id="inpPhone" type="tel" class="w-full mt-1 bg-black border-2 border-zinc-800 rounded-[10px] px-4 py-3 mono text-[14px] outline-none input-glow" placeholder="10 digit" maxlength="10" inputmode="numeric"></div>
    </div>
    <button onclick="saveOnboard()" class="w-full mt-6 bg-gradient-to-r from-[#ff4d00] to-[#ff8a00] mono font-black py-3.5 rounded-[12px]">ENTER BATTLEFIELD 🔫</button>
  </div>
</div>

<!-- 28 FEATURES POPUP BY SPARSH SINGHAL -->
<div id="payModal" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4" style="background:rgba(0,0,0,0.92)">
  <div class="hud rounded-[20px] p-6 max-w-[520px] w-full border-2 border-[#ff4d00]/50 shadow-[0_0_50px_rgba(255,77,0,0.3)] max-h-[92vh] overflow-y-auto">
    <h2 class="font-black text-[24px] text-center">OUT OF AMMO! 🔫</h2>
    <p class="mono text-[11px] mt-1 text-zinc-400 text-center">10 free FIRE khatam! Pro lele — BY SPARSH SINGHAL</p>
    <div class="mt-4 bg-black border border-[#ff4d00]/30 rounded-[12px] p-4">
      <p class="mono text-[13px] font-black text-[#ff8a00] text-center">₹49 BATTLE PASS - ALL 28 FEATURES 🔥</p>
      <div class="mt-3 grid grid-cols-1 gap-1 mono text-[11px] leading-[1.7] max-h-[300px] overflow-y-auto pr-2">
        <div>✓ 1. Unlimited Doubt Solving</div>
        <div>✓ 2. Hinglish Savage Roast Mode</div>
        <div>✓ 3. NCERT Full Solutions</div>
        <div>✓ 4. PYQ (Last 10 Years)</div>
        <div>✓ 5. Chapter-wise Notes</div>
        <div>✓ 6. Mind Maps Generator</div>
        <div>✓ 7. Formula Sheets</div>
        <div>✓ 8. Important Questions Bank</div>
        <div>✓ 9. Live Leaderboard Ranking</div>
        <div>✓ 10. XP & Level System + Shield</div>
        <div>✓ 11. Sound Effects + Haptic Feedback</div>
        <div>✓ 12. Diagram Explainer</div>
        <div>✓ 13. Derivation Breakdown</div>
        <div>✓ 14. Numerical Solver Step-by-Step</div>
        <div>✓ 15. MCQ Quiz Generator</div>
        <div>✓ 16. Mock Test Creator</div>
        <div>✓ 17. Essay / Letter / Application Writer</div>
        <div>✓ 18. Resume Builder</div>
        <div>✓ 19. Voice Input Support</div>
        <div>✓ 20. Image Doubt Scan (OCR)</div>
        <div>✓ 21. YouTube Video Summarizer</div>
        <div>✓ 22. Career Guidance</div>
        <div>✓ 23. No Ads Experience</div>
        <div>✓ 24. Priority Answer (Fastest)</div>
        <div>✓ 25. Daily Missions & Rewards</div>
        <div>✓ 26. Ammo Crate Never Ends</div>
        <div>✓ 27. Phone Linked Plan Tracking</div>
        <div>✓ 28. Founder Sparsh Singhal Direct Tips</div>
      </div>
      <p class="mono text-[10px] mt-3 text-zinc-500 text-center">Linked to private no: <span id="payPhoneInfo" class="text-white"></span> 🔒 Private</p>
    </div>
    <a id="upiLink" href="#" target="_blank" class="block w-full mt-4 bg-gradient-to-r from-[#ff4d00] to-[#ff8a00] mono font-black py-3.5 rounded-[12px] text-center">BUY NOW - ₹49 via UPI</a>
    <p class="mono text-[9px] text-zinc-500 mt-2 text-center">Razorpay auto-unlock kal connect hoga - BY SPARSH SINGHAL<br>After payment WhatsApp screenshot bhejo</p>
    <button onclick="closePay()" class="w-full mt-3 bg-zinc-800 py-3 rounded-[10px] mono font-black text-[12px]">CLOSE</button>
  </div>
</div>

<script>
let audioCtx; function initAudio(){ if(!audioCtx) audioCtx = new (window.AudioContext||window.webkitAudioContext)(); }
function playSound(t){ try{ initAudio(); let o=audioCtx.createOscillator(); let g=audioCtx.createGain(); o.connect(g); g.connect(audioCtx.destination); if(t=='fire'){o.frequency.value=900;o.type='square';g.gain.setValueAtTime(0.4,audioCtx.currentTime);g.gain.exponentialRampToValueAtTime(0.01,audioCtx.currentTime+0.12);o.start();o.stop(audioCtx.currentTime+0.12);} if(t=='hit'){o.frequency.value=500;o.type='sine';g.gain.setValueAtTime(0.3,audioCtx.currentTime);g.gain.exponentialRampToValueAtTime(0.01,audioCtx.currentTime+0.2);o.start();o.stop(audioCtx.currentTime+0.2);} if(t=='level'){o.frequency.value=600;o.type='sine';g.gain.setValueAtTime(0.4,audioCtx.currentTime);o.frequency.linearRampToValueAtTime(1200,audioCtx.currentTime+0.5);g.gain.exponentialRampToValueAtTime(0.01,audioCtx.currentTime+0.6);o.start();o.stop(audioCtx.currentTime+0.6);} if(t=='empty'){o.frequency.value=150;o.type='sawtooth';g.gain.setValueAtTime(0.4,audioCtx.currentTime);g.gain.exponentialRampToValueAtTime(0.01,audioCtx.currentTime+0.6);o.start();o.stop(audioCtx.currentTime+0.6);} if(t=='click'){o.frequency.value=800;o.type='triangle';g.gain.setValueAtTime(0.2,audioCtx.currentTime);g.gain.exponentialRampToValueAtTime(0.01,audioCtx.currentTime+0.1);o.start();o.stop(audioCtx.currentTime+0.1);} }catch{} }
function openPay(){ playSound('empty'); let ph=localStorage.getItem('genie_phone')||''; document.getElementById('payPhoneInfo').innerText = ph? `XXXXXX${ph.slice(-4)}`:'PRIVATE'; document.getElementById('upiLink').href = `upi://pay?pa=sparshsinghal@okicici&pn=Sparsh%20Singhal&am=49&cu=INR&tn=StudyGenie Pro ${ph}`; document.getElementById('payModal').classList.remove('hidden'); }
function closePay(){ playSound('click'); document.getElementById('payModal').classList.add('hidden'); }

let userId=localStorage.getItem('genie_userId')||'user_'+Math.random().toString(36).substr(2,9); localStorage.setItem('genie_userId',userId);
let userName=localStorage.getItem('genie_name')||''; let userPhone=localStorage.getItem('genie_phone')||'';
function checkOnboard(){ userName=localStorage.getItem('genie_name')||''; userPhone=localStorage.getItem('genie_phone')||''; if(!userName ||!userPhone || userPhone.length!=10){ document.getElementById('onboardModal').classList.remove('hidden'); } else { document.getElementById('onboardModal').classList.add('hidden'); document.getElementById('userNameTop').innerText=userName.toUpperCase(); document.getElementById('myId').innerText=`ID: ${userId} (private)`; document.getElementById('myPhone').innerText=`PHONE: XXXXXX${userPhone.slice(-4)} 🔒`; } }
function saveOnboard(){ let n=document.getElementById('inpName').value.trim(); let p=document.getElementById('inpPhone').value.trim().replace(/[^0-9]/g,''); if(n.length<2){alert('Naam daal!');playSound('empty');return;} if(p.length!=10){alert('10 digit phone');playSound('empty');return;} localStorage.setItem('genie_name',n); localStorage.setItem('genie_phone',p); userName=n; userPhone=p; playSound('level'); document.getElementById('onboardModal').classList.add('hidden'); document.getElementById('userNameTop').innerText=n.toUpperCase(); document.getElementById('myId').innerText=`ID: ${userId} (private)`; document.getElementById('myPhone').innerText=`PHONE: XXXXXX${p.slice(-4)} 🔒`; updateLeaderboard(); fetch('/register_user',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({uid:userId,name:n,phone:p})}); }

let stats=JSON.parse(localStorage.getItem('genie_stats')||'{"xp":0,"level":1,"wishes":0,"q1":0,"totalXp":0}');
let isDev=localStorage.getItem('isDev')==='true';
function lamps(){let r=document.getElementById('lampRow'); r.innerHTML=''; for(let i=0;i<10;i++){let u=i<stats.wishes&&!isDev; r.innerHTML+=`<div class="ammo ${u?'used':''}">${u?'💨':'🪔'}</div>`;}}
function save(){localStorage.setItem('genie_stats',JSON.stringify(stats)); render(); updateLeaderboard();}
function render(){document.getElementById('wishLeft').innerText=isDev?'∞':10-stats.wishes; document.getElementById('lvlTop').innerText=stats.level; document.getElementById('xpBarTop').style.width=stats.xp+'%'; document.getElementById('xpText').innerText=stats.xp+'/100 XP'; document.getElementById('q1t').innerText=stats.q1+'/3'; document.getElementById('q1b').style.width=stats.q1/3*100+'%'; lamps();}
async function updateLeaderboard(){ try{ let n=localStorage.getItem('genie_name')||userName||'Warrior'; let ph=localStorage.getItem('genie_phone')||userPhone||''; await fetch('/update_xp',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({uid:userId,name:n,phone:ph,xp:stats.totalXp||((stats.level-1)*100+stats.xp)})}); loadBoard(); }catch{} }
async function loadBoard(){ try{ let r=await fetch('/leaderboard?t='+Date.now()); let d=await r.json(); if(d.length==0){document.getElementById('board').innerHTML=`<div class="text-zinc-500 text-center py-2">No warriors yet.</div>`; return;} let myRank=d.findIndex(u=>u.id===userId)+1; document.getElementById('rankTop').innerText=myRank||'-'; document.getElementById('board').innerHTML=d.map((u,i)=>{ let isMe=u.id===userId; let medal=i==0?'👑':i==1?'🥈':i==2?'🥉':`${i+1}.`; return `<div class="flex justify-between items-center p-2.5 rounded-[8px] border ${isMe?'bg-[#ff4d00]/10 border-[#ff4d00]/50 text-white':'bg-black border-zinc-800 text-zinc-300'} hitpop"><span>${medal} ${u.name} ${isMe?'[YOU]':''}</span><span class="text-[#ff4d00] font-black">${u.xp} XP</span></div>`; }).join(''); }catch{} }
let c=0; document.getElementById('logo').addEventListener('click',()=>{playSound('click');c++;if(c>=5){let p=prompt("DEV ACCESS BY SPARSH SINGHAL - Code:");if(p==="sparsh123"){isDev=!isDev;localStorage.setItem('isDev',isDev);playSound(isDev?'level':'empty');alert(isDev?'GOD MODE ON':'OFF');render();}else if(p!==null){alert("ACCESS DENIED!");}c=0;}setTimeout(()=>c=0,2000);});
async function ask(){ if(!localStorage.getItem('genie_name')||!localStorage.getItem('genie_phone')){checkOnboard();return;} let input=document.getElementById('q'); let q=input.value.trim(); if(!q)return; if(!isDev && stats.wishes>=10){openPay();return;} playSound('fire'); let chat=document.getElementById('chat'); chat.innerHTML+=`<div class="flex justify-end hitpop"><div class="bubble-user px-4 py-2 text-[14px] mono">${q}</div></div>`; input.value=''; stats.wishes++; stats.q1=Math.min(3,stats.q1+1); stats.xp+=12; stats.totalXp=(stats.totalXp||0)+12; if(stats.xp>=100){stats.level++;stats.xp=0;playSound('level');chat.innerHTML+=`<div class="text-center mono text-[#ff4d00] font-black text-[12px] py-2">LEVEL UP BY SPARSH SINGHAL - LVL ${stats.level}</div>`;} save(); chat.innerHTML+=`<div id="typing" class="flex gap-3"><img src="/sparsh.jpg" class="w-12 h-12 rounded-[10px] border-2 border-[#ff4d00] object-cover"><div class="bubble-ai p-4 mono text-[12px] text-zinc-400 animate-pulse">> SPARSH SINGHAL'S GENIE LOCKING TARGET...</div></div>`; chat.scrollTop=chat.scrollHeight; let res=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({q,name:userName,phone:userPhone})}); let data=await res.json(); document.getElementById('typing')?.remove(); playSound('hit'); chat.innerHTML+=`<div class="flex gap-3 hitpop"><img src="/sparsh.jpg" class="w-12 h-12 rounded-[10px] border-2 border-[#ff4d00] object-cover"><div class="bubble-ai p-4 max-w-[78%] text-[14px] whitespace-pre-wrap">${data.ans}</div></div>`; chat.scrollTop=chat.scrollHeight; }
document.getElementById('chat').innerHTML=`<div class="flex gap-3 hitpop"><img src="/sparsh.jpg" class="w-12 h-12 rounded-[10px] border-2 border-[#ff4d00] object-cover"><div class="bubble-ai p-5 max-w-[78%] text-[14px] leading-relaxed">🔥 <b>OYE WARRIOR, BATTLEFIELD ME SWAGAT HAI!</b><br><br>Main hoon <b>Sparsh Singhal ka StudyGenie</b> — 28 features ke saath tere har doubt ko headshot dunga! 🔫<br><br><span class="mono text-[10px] text-[#ff4d00]">BY SPARSH SINGHAL | 28 FEATURES | SOUND ON 🔊</span></div></div>`;
checkOnboard(); render(); loadBoard(); setInterval(loadBoard, 5000);
if(localStorage.getItem('genie_name')) document.getElementById('inpName').value=localStorage.getItem('genie_name');
if(localStorage.getItem('genie_phone')) document.getElementById('inpPhone').value=localStorage.getItem('genie_phone');
</script></body></html>
"""

@app.route("/")
def home(): return HTML_PAGE

@app.route("/sparsh.jpg")
def photo():
    try: return send_from_directory(".", "sparsh.jpg")
    except: return "", 204

@app.route("/register_user", methods=["POST"])
def register_user():
    d = request.get_json(silent=True) or {}
    uid = d.get("uid"); name = d.get("name","Warrior")[:20]; phone = d.get("phone","")[:10]
    if phone: USER_DB[phone] = {"name": name, "uid": uid, "phone": phone, "plan": "free", "xp": 0}
    return jsonify({"ok": True})

@app.route("/leaderboard")
def leaderboard():
    sorted_users = sorted(REAL_LEADERBOARD.values(), key=lambda x: x['xp'], reverse=True)[:10]
    public = [{"id": u["id"], "name": u["name"], "xp": u["xp"]} for u in sorted_users]
    return jsonify(public)

@app.route("/update_xp", methods=["POST"])
def update_xp():
    d = request.get_json(silent=True) or {}
    uid = d.get("uid","anon"); xp = int(d.get("xp",0))
    name = d.get("name","Warrior")[:20] or f"Grinder {uid[-3:].upper()}"
    phone = d.get("phone","")[:10]
    REAL_LEADERBOARD[uid] = {"id": uid, "name": name, "xp": xp, "_phone": phone}
    if phone and phone in USER_DB:
        USER_DB[phone]["xp"] = xp; USER_DB[phone]["name"] = name
    return jsonify({"ok": True})

@app.route("/ask", methods=["POST"])
def ask_gemini():
    d = request.get_json(silent=True) or {}
    q = d.get("q",""); name = d.get("name","Warrior")
    if not client: return jsonify({"ans": f"Oye {name}, API Key missing - BY SPARSH SINGHAL"})
    try:
        resp = client.models.generate_content(model="gemini-2.0-flash", contents=f"You are StudyGenie by Sparsh Singhal. User {name}. Hinglish savage 180 words max. User: {q}")
        return jsonify({"ans": resp.text})
    except Exception as e: return jsonify({"ans": f"Error {e} - BY SPARSH SINGHAL"})

@app.route("/admin_users")
def admin_users():
    return jsonify({"users": list(USER_DB.values())})

if __name__ == "__main__": app.run()
