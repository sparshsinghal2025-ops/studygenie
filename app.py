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
.ammo.used{opacity:.15}
.progress{height:12px;background:#0f0f11;border:1px solid #2a2a2e;transform:skew(-10deg);border-radius:2px;overflow:hidden}
.progress>div{height:100%;background:linear-gradient(90deg,#ff4d00,#ff8a00)}
#chat{max-height:62vh;overflow-y:auto!important;scroll-behavior:smooth}
</style>
</head>
<body class="p-3">
<div class="max-w-[1450px] mx-auto pb-20">
<div class="hud rounded-[16px] px-5 py-3 flex justify-between items-center sticky top-2 z-30">
  <div class="flex items-center gap-6">
    <img id="logo" src="/sparsh.jpg" class="w-28 h-28 rounded-[16px] border-[4px] border-[#ff4d00] object-cover shadow-[0_0_40px_rgba(255,77,0,0.7)] cursor-pointer">
    <div><h1 class="font-black text-[22px] tracking-widest">STUDYGENIE <span class="text-[#ff4d00]">: BATTLE</span></h1><p class="mono text-[12px] text-[#ff8a00] mt-1">BY SPARSH SINGHAL // FOUNDER</p><div class="flex items-center gap-3 mt-3"><span class="mono text-[10px] text-zinc-400">SHIELD</span><div class="w-40 progress"><div id="xpBarTop" style="width:0%"></div></div><span id="xpText" class="mono text-[11px] font-bold">0/100 XP</span></div></div>
  </div>
  <div class="mono text-right"><div class="text-[10px] text-zinc-500">AMMO</div><div class="font-black text-3xl"><span id="wishLeft">10</span>/10</div></div>
</div>
<div class="grid grid-cols-12 gap-3 mt-3">
  <div class="col-span-12 lg:col-span-3 space-y-3">
    <div class="hud rounded-[14px] p-4"><p class="mono text-[10px] text-zinc-500">> MISSIONS BY SPARSH SINGHAL</p><div class="mt-4 bg-black p-3 rounded-[10px] border-l-[3px] border-[#ff4d00]"><div class="flex justify-between mono text-[11px] font-bold"><span>ELIMINATE 3 DOUBTS</span><span id="q1t">0/3</span></div><div class="progress mt-2"><div id="q1b" style="width:0%"></div></div></div></div>
    <div class="hud rounded-[14px] p-4"><p class="mono text-[10px] text-zinc-500">> AMMO CRATE</p><div id="lampRow" class="grid grid-cols-5 gap-2 mt-3"></div><button onclick="document.getElementById('payModal').classList.remove('hidden')" class="w-full mt-4 bg-[#ff4d00] mono font-black py-3 rounded-[10px]">RELOAD - ₹49</button></div>
  </div>
  <div class="col-span-12 lg:col-span-9 hud rounded-[16px] p-4 flex flex-col">
    <div id="chat" class="flex-1 space-y-4 pr-2"></div>
    <div class="mt-4 bg-black border-2 border-[#2a2a2e] rounded-[12px] p-1.5 flex items-center gap-2 sticky bottom-2"><input id="q" class="flex-1 bg-transparent mono text-[14px] outline-none py-3 px-3" placeholder="ENTER COMMAND BY SPARSH SINGHAL..." onkeypress="if(event.key==='Enter')ask()"><button onclick="ask()" class="bg-[#ff4d00] mono font-black w-20 h-11 rounded-[10px]">FIRE</button></div>
  </div>
</div>
</div>
<div id="payModal" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4" style="background:rgba(0,0,0,0.9)"><div class="hud rounded-[20px] p-6 max-w-[400px] w-full text-center border-2 border-[#ff4d00]/50"><h2 class="font-black text-2xl">OUT OF AMMO!</h2><button onclick="document.getElementById('payModal').classList.add('hidden')" class="w-full mt-4 bg-[#ff4d00] py-3 rounded-[10px] mono font-black">CLOSE</button></div></div>
<script>
let userId=localStorage.getItem('genie_userId')||'user_'+Math.random().toString(36).substr(2,9); localStorage.setItem('genie_userId',userId);
let stats=JSON.parse(localStorage.getItem('genie_stats')||'{"xp":0,"level":1,"wishes":0,"q1":0}');
let isDev=localStorage.getItem('isDev')==='true';
function lamps(){let r=document.getElementById('lampRow'); r.innerHTML=''; for(let i=0;i<10;i++){let u=i<stats.wishes&&!isDev; r.innerHTML+=`<div class="ammo ${u?'used':''}">${u?'💨':'🪔'}</div>`;}}
function save(){localStorage.setItem('genie_stats',JSON.stringify(stats)); render();}
function render(){document.getElementById('wishLeft').innerText=isDev?'∞':10-stats.wishes; document.getElementById('lvlTop')?.innerText; document.getElementById('xpBarTop').style.width=stats.xp+'%'; document.getElementById('xpText').innerText=stats.xp+'/100 XP'; document.getElementById('q1t').innerText=stats.q1+'/3'; document.getElementById('q1b').style.width=stats.q1/3*100+'%'; lamps();}
let c=0; document.getElementById('logo').addEventListener('click',()=>{ c++; if(c>=5){ let p=prompt("DEV ACCESS - Secret Code:"); if(p==="sparsh123"){isDev=!isDev; localStorage.setItem('isDev',isDev); alert(isDev?'GOD MODE ON':'GOD MODE OFF'); render();} else if(p!==null){alert("ACCESS DENIED!");} c=0;} setTimeout(()=>c=0,2000); });
async function ask(){
  let input=document.getElementById('q'); let q=input.value.trim(); if(!q) return;
  if(!isDev && stats.wishes>=10){document.getElementById('payModal').classList.remove('hidden'); return;}
  let chat=document.getElementById('chat'); chat.innerHTML+=`<div class="flex justify-end"><div class="bubble-user px-4 py-2 text-[14px] mono">${q}</div></div>`; input.value='';
  stats.wishes++; stats.q1=Math.min(3,stats.q1+1); stats.xp+=12; if(stats.xp>=100){stats.level++; stats.xp=0;} save();
  chat.innerHTML+=`<div id="typing" class="mono text-[12px] text-zinc-400">> Genie aiming...</div>`; chat.scrollTop=chat.scrollHeight;
  let res=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({q})}); let data=await res.json();
  document.getElementById('typing')?.remove();
  chat.innerHTML+=`<div class="flex gap-3"><img src="/sparsh.jpg" class="w-12 h-12 rounded-[10px] border-2 border-[#ff4d00] object-cover"><div class="bubble-ai p-4 max-w-[78%] text-[14px] whitespace-pre-wrap">${data.ans}</div></div>`;
  chat.scrollTop=chat.scrollHeight;
}
document.getElementById('chat').innerHTML=`<div class="flex gap-3"><img src="/sparsh.jpg" class="w-12 h-12 rounded-[10px] border-2 border-[#ff4d00] object-cover"><div class="bubble-ai p-4 max-w-[78%] text-[14px]">WELCOME TO BATTLEFIELD BY SPARSH SINGHAL. Scroll fixed hai!</div></div>`; render();
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
        resp = client.models.generate_content(model="gemini-3.6-flash", contents=f"You are StudyGenie by Sparsh Singhal, Hinglish savage. User: {q}")
        return jsonify({"ans": resp.text})
    except Exception as e: return jsonify({"ans": f"Error {e}"})

if __name__ == "__main__": app.run()
