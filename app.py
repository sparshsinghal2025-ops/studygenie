import os
from flask import Flask, request, jsonify, send_from_directory, render_template_string
from google import genai

app = Flask(__name__)
API_KEY = os.environ.get("GOOGLE_API_KEY", "")
client = genai.Client(api_key=API_KEY) if API_KEY else None

# REAL USERS ONLY - no fake
REAL_LEADERBOARD = {}

HTML_PAGE = """
<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>StudyGenie by Sparsh Singhal</title>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;700;900&display=swap" rel="stylesheet">
<style>
body{font-family:'Outfit',sans-serif; background: radial-gradient(ellipse at top, #2a2a6a 0%, #1e1b4b 60%, #0f0f23 100%); color:white; min-height:100vh}
.glass{background: rgba(255,255,255,0.07); backdrop-filter: blur(20px); border:1px solid rgba(255,255,255,0.12); box-shadow: 0 8px 32px rgba(0,0,0,0.3)}
.bubble-user{background: linear-gradient(135deg, #ff7a18, #ff5a00); box-shadow: 0 4px 15px rgba(255,90,0,0.4)}
.bubble-ai{background: rgba(255,255,255,0.11); border:1px solid rgba(255,255,255,0.15)}
.modal-bg{background: rgba(0,0,0,0.75); backdrop-filter: blur(12px)}
#chat::-webkit-scrollbar{width:5px} #chat::-webkit-scrollbar-thumb{background:#ff7a18; border-radius:10px}
.chip{cursor:pointer; transition: all 0.2s}.chip:hover{transform:translateY(-2px); background: rgba(255,122,24,0.25); border-color: #ff7a18}
</style>
</head>
<body class="p-3 md:p-5">
<div class="flex justify-between items-center glass rounded-2xl px-4 py-3 mb-4">
  <div class="flex items-center gap-3">
    <img id="logo" src="/sparsh.jpg" class="w-12 h-12 md:w-14 md:h-14 rounded-full border-2 border-orange-500 object-cover cursor-pointer shadow-lg" title="Dev: 5x click">
    <div>
      <h1 class="text-lg md:text-2xl font-black">StudyGenie <span class="text-orange-400">by Sparsh</span> <span id="devBadge" class="hidden text-[9px] bg-yellow-400 text-black px-2 py-0.5 rounded-full ml-1">DEV UNLIMITED 👑</span></h1>
      <p class="text-[11px] md:text-xs opacity-70"><span id="wishLeft">10</span> wishes left • Level <span id="lvl">1</span> • <span id="rank">#1</span></p>
    </div>
  </div>
  <button id="voiceBtn" onclick="toggleVoice()" class="px-3 md:px-4 py-1.5 rounded-full text-xs font-bold bg-green-500/20 border border-green-500">🔊 Voice: ON</button>
</div>

<div class="grid grid-cols-1 lg:grid-cols-4 gap-4">
  <div class="lg:col-span-3 glass rounded-[24px] p-3 md:p-4 flex flex-col min-h-[75vh]">
    <div id="chat" class="flex-1 space-y-4 overflow-y-auto pr-1 max-h-[60vh] md:max-h-[65vh]">
      <div class="bubble-ai p-4 rounded-2xl rounded-bl-none max-w-[92%] text-sm leading-relaxed">Hukm mere aaka! 🧞 <b>Mai Sparsh ka Genie hu!</b> Ab leaderboard 100% real hai, 10 free wishes milengi! 😎</div>
    </div>
    <div class="flex gap-2 mt-4 flex-wrap">
      <span class="chip glass px-3 py-1.5 rounded-full text-xs border border-white/10" onclick="quickAsk('Linked List samjha de masti me')">📚 Linked List</span>
      <span class="chip glass px-3 py-1.5 rounded-full text-xs border border-white/10" onclick="quickAsk('photosynthesis samjhao easy me')">🌿 Photosynthesis</span>
      <span class="chip glass px-3 py-1.5 rounded-full text-xs border border-white/10" onclick="quickAsk('Ek joke suna Genie style me')">😂 Joke</span>
      <span class="chip glass px-3 py-1.5 rounded-full text-xs border border-white/10" onclick="quickAsk('Mera roast kar de')">🔥 Roast</span>
    </div>
    <div class="mt-4 flex gap-2 items-center glass rounded-full p-1.5">
      <input id="q" class="flex-1 bg-transparent px-4 py-2 outline-none text-sm placeholder-white/40" placeholder="Bol aaka kya chahiye..." onkeypress="if(event.key==='Enter')ask()">
      <button onclick="ask()" class="bg-gradient-to-r from-orange-500 to-orange-600 px-6 md:px-8 py-2.5 rounded-full font-black text-sm shadow-lg">GO</button>
    </div>
  </div>

  <div class="space-y-3">
    <div class="glass p-4 rounded-2xl">
      <div class="flex justify-between"><h3 class="font-black text-sm">Wishes <span class="text-orange-400">Free</span></h3><span id="wishes" class="text-xs font-bold">0 / 10</span></div>
      <div class="h-2 bg-black/30 rounded-full mt-3"><div id="wishBar" class="bg-gradient-to-r from-orange-500 to-yellow-400 h-2 rounded-full transition-all duration-500" style="width:0%"></div></div>
      <p class="text-[11px] mt-2 opacity-60">10 free, fir Pro 🔒</p>
    </div>
    <div class="glass p-4 rounded-2xl">
      <h3 class="font-bold text-sm flex items-center gap-2">🏆 Live Leaderboard <span class="text-[8px] bg-green-500/30 border border-green-500 px-2 py-0.5 rounded-full">REAL</span></h3>
      <div id="board" class="mt-3 space-y-2 text-xs"><p class="opacity-50">Loading real grinders...</p></div>
      <p class="text-[10px] mt-3 opacity-40">Only real users • Auto refresh 5s</p>
    </div>
    <div class="glass p-4 rounded-2xl">
      <p class="font-bold text-sm">⚡ Your Stats</p>
      <p class="text-xs mt-1 opacity-80">XP: <span id="xp">0</span> • Level <span id="lvl2">1</span></p>
      <div class="h-2 bg-black/30 rounded-full mt-2"><div id="xpBar" class="bg-gradient-to-r from-yellow-300 to-orange-400 h-2 rounded-full transition-all" style="width:0%"></div></div>
      <p class="text-[10px] mt-2 opacity-50">Har sawal = +12 XP</p>
    </div>
  </div>
</div>

<div id="payModal" class="hidden fixed inset-0 modal-bg flex items-center justify-center z-50 p-4">
  <div class="glass rounded-[24px] p-6 max-w-sm w-full text-center border border-orange-500/30">
    <h2 class="text-2xl font-black">🔒 10 Wishes Khatam!</h2>
    <p class="text-sm mt-2 opacity-80">Aaka, free ki wishes khatam ho gayi. Genie ab Pro maang raha hai!</p>
    <div class="mt-4 bg-black/30 rounded-2xl p-4 text-left text-xs space-y-2"><p>✅ Unlimited wishes</p><p>✅ Voice never stops</p><p>✅ Leaderboard boost</p><p>✅ No limits</p></div>
    <div class="mt-4 grid grid-cols-2 gap-2"><button onclick="buyPro()" class="bg-gradient-to-r from-orange-500 to-yellow-500 text-black font-black py-3 rounded-full">Buy Pro ₹99/m</button><button onclick="closePay()" class="glass py-3 rounded-full text-sm">Baad me</button></div>
    <p class="text-[10px] mt-3 opacity-40">Dev? Logo pe 5x click karo 😉</p>
  </div>
</div>

<script>
let voiceOn=true, synth=window.speechSynthesis, queue=[], isSpeaking=false;
let userId = localStorage.getItem('genie_userId') || 'user_'+Math.random().toString(36).substr(2,9);
localStorage.setItem('genie_userId', userId);
let stats = JSON.parse(localStorage.getItem('genie_stats') || '{"xp":0,"level":1,"wishes":0}');
let isDev = localStorage.getItem('isDev')==='true';

function save(){localStorage.setItem('genie_stats', JSON.stringify(stats)); render();}
function render(){
  let left = isDev? '∞' : Math.max(0, 10-stats.wishes);
  document.getElementById('wishes').innerText = isDev? stats.wishes+' / ∞' : stats.wishes+' / 10';
  document.getElementById('wishLeft').innerText = left;
  document.getElementById('xp').innerText = stats.xp + (stats.level-1)*100;
  document.getElementById('lvl').innerText = stats.level;
  document.getElementById('lvl2').innerText = stats.level;
  document.getElementById('wishBar').style.width = isDev? '100%' : (stats.wishes*10)+'%';
  document.getElementById('xpBar').style.width = (stats.xp % 100)+'%';
  document.getElementById('devBadge').classList.toggle('hidden',!isDev);
  loadBoard();
}
async function loadBoard(){
  try{
    let r=await fetch('/leaderboard?uid='+userId); let data=await r.json();
    if(data.length===0){document.getElementById('board').innerHTML='<p class="opacity-50">Tu pehla grinder hai! 🔥 Sawal puch ranking me aa</p>'; return;}
    let html=''; data.forEach((u,i)=>{
      let isMe = u.id===userId;
      html+=`<div class="flex justify-between p-1.5 rounded-lg ${isMe?'bg-orange-500/20 text-orange-400 font-bold border border-orange-500/30':''}"><span>${i+1}. ${u.name} ${isMe?'(You)':''} ${isMe && isDev?'👑':''}</span><span>${u.xp} XP</span></div>`;
      if(isMe) document.getElementById('rank').innerText = '#'+(i+1);
    });
    document.getElementById('board').innerHTML=html;
  }catch{}
}
let clicks=0; document.getElementById('logo').addEventListener('click', ()=>{clicks++; if(clicks>=5){isDev=!isDev; localStorage.setItem('isDev', isDev); alert(isDev?'DEV MODE ON - Unlimited! 👑':'DEV MODE OFF'); clicks=0; render();} setTimeout(()=>clicks=0,2000);});
function toggleVoice(){voiceOn=!voiceOn; document.getElementById('voiceBtn').innerHTML=voiceOn?'🔊 Voice: ON':'🔇 Voice: OFF'; if(!voiceOn){synth.cancel(); queue=[]; isSpeaking=false;}}
function cleanForSpeech(t){return t.replace(/<[^>]*>/g,'').replace(/[*#_`~]/g,'').replace(/[\\u{1F600}-\\u{1F64F}\\u{1F300}-\\u{1F5FF}\\u{1F680}-\\u{1F6FF}\\u{2600}-\\u{26FF}\\u{2700}-\\u{27BF}]/gu,'').trim();}
function speakQueue(txt){if(!voiceOn) return; let c=cleanForSpeech(txt); let s=c.match(/[^.!?]+[.!?]+|[\\s\\S]{1,140}(?=\\s|$)/g)||[c]; queue.push(...s); if(!isSpeaking) playNext();}
function playNext(){if(queue.length==0){isSpeaking=false; return;} isSpeaking=true; let u=new SpeechSynthesisUtterance(queue.shift()); u.lang='hi-IN'; u.rate=1.02; let v=synth.getVoices().find(x=>x.lang.includes('hi'))||synth.getVoices()[0]; if(v) u.voice=v; u.onend=()=>playNext(); u.onerror=()=>playNext(); synth.speak(u);}
function closePay(){document.getElementById('payModal').classList.add('hidden');}
function buyPro(){alert("Razorpay link yahan lagega!"); closePay();}
function quickAsk(t){document.getElementById('q').value=t; ask();}
async function ask(){
  let input=document.getElementById('q'); let q=input.value.trim(); if(!q) return;
  if(!isDev && stats.wishes>=10){document.getElementById('payModal').classList.remove('hidden'); return;}
  let chat=document.getElementById('chat'); chat.innerHTML+=`<div class="bubble-user p-3 px-4 rounded-2xl rounded-br-none max-w-[85%] ml-auto text-sm font-medium">${q}</div>`; input.value='';
  stats.wishes++; stats.xp+=12; if(stats.xp>=100){stats.level++; stats.xp=0;} save();
  fetch('/update_xp',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({uid:userId, xp: (stats.level-1)*100 + stats.xp + stats.wishes*2, level:stats.level})});
  chat.innerHTML+=`<div id="typing" class="bubble-ai p-3 rounded-2xl max-w-[40%] text-xs opacity-70 flex items-center gap-2"><span class="w-2 h-2 bg-orange-400 rounded-full animate-bounce"></span> Genie soch raha hai...</div>`; chat.scrollTop=chat.scrollHeight;
  let res=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({q})}); let data=await res.json();
  document.getElementById('typing')?.remove();
  let id=Date.now(); chat.innerHTML+=`<div class="bubble-ai p-4 rounded-2xl rounded-bl-none max-w-[92%] text-[13px] leading-relaxed whitespace-pre-wrap"><span id="ans-${id}">${data.ans}</span><div class="mt-3 flex gap-2"><button onclick="speakQueue(document.getElementById('ans-${id}').innerText)" class="text-[11px] glass px-3 py-1 rounded-full hover:bg-white/20">🔊 Pura suna de</button><button onclick="navigator.clipboard.writeText(document.getElementById('ans-${id}').innerText)" class="text-[11px] glass px-3 py-1 rounded-full hover:bg-white/20">📋 Copy</button></div></div>`;
  chat.scrollTop=chat.scrollHeight; speakQueue(data.ans);
}
render(); setInterval(loadBoard, 5000);
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
    sorted_users = sorted(REAL_LEADERBOARD.values(), key=lambda x: x['xp'], reverse=True)
    return jsonify(sorted_users[:10])

@app.route("/update_xp", methods=["POST"])
def update_xp():
    data = request.json
    uid = data.get("uid")
    xp = data.get("xp",0)
    level = data.get("level",1)
    if uid:
        REAL_LEADERBOARD[uid] = {"id":uid, "name": f"Grinder {uid[-3:].upper()}", "xp":xp, "level":level}
    return jsonify({"ok":True})

@app.route("/ask", methods=["POST"])
def ask_gemini():
    q=request.json.get("q","")
    if not client: return jsonify({"ans":"API Key missing! Vercel me GOOGLE_API_KEY add kar"})
    try:
        prompt=f"You are StudyGenie by Sparsh Singhal, funny Gen-Z Hinglish Genie. Max 180 words, use emojis, bullets, end with question. User: {q}"
        resp=client.models.generate_content(model="gemini-3.6-flash", contents=prompt)
        return jsonify({"ans":resp.text})
    except Exception as e: return jsonify({"ans":f"Error: {str(e)}"})

if __name__=="__main__": app.run()
