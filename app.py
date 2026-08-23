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
<title>StudyGenie - Level Up Your Brain</title>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@600;800&family=Space+Grotesk:wght@700&display=swap" rel="stylesheet">
<style>
*{font-family:'Outfit',sans-serif}
body{background:#08070f!important; color:white; overflow:hidden}
.glass{background:linear-gradient(180deg, rgba(24,20,40,0.9), rgba(12,12,20,0.9))!important; border:1px solid rgba(255,255,255,0.08)!important}
.bubble-user{background:linear-gradient(135deg,#ff7a00,#ffb700); box-shadow:0 0 20px rgba(255,122,0,0.4)}
.bubble-ai{background:#17151f; border:1px solid #2a2840}
.lamp{transition:0.5s cubic-bezier(.34,1.56,.64,1)}.lamp.off{filter:grayscale(1) opacity(0.2); transform:scale(0.7) rotate(15deg)}
@keyframes xpPop{0%{transform:translateY(0) scale(1)}100%{transform:translateY(-60px) scale(1.3); opacity:0}}.xp-pop{animation:xpPop 1s ease-out forwards}
.quest-done{background:#00ff88!important; color:black!important}
.shimmer{position:relative; overflow:hidden}.shimmer:after{content:''; position:absolute; top:0; left:-100%; width:200%; height:100%; background:linear-gradient(90deg,transparent,rgba(255,255,255,0.2),transparent); animation:shim 2s infinite} @keyframes shim{100%{left:100%}}
</style>
</head>
<body class="p-2 md:p-3">
<div class="flex justify-between items-center glass rounded-[16px] px-4 py-2.5 max-w-[1400px] mx-auto">
  <div class="flex items-center gap-3"><img id="logo" src="/sparsh.jpg" class="w-10 h-10 rounded-full border-2 border-orange-400"><div><h1 class="font-black text-[15px]" style="font-family:'Space Grotesk'">StudyGenie</h1><p class="text-[10px] opacity-60">by Sparsh • Level <span id="lvlTop">1</span></p></div>
  <div class="ml-4 w-28 h-2 bg-black/60 rounded-full overflow-hidden"><div id="xpBarTop" class="h-full bg-gradient-to-r from-orange-400 to-yellow-300" style="width:10%"></div></div></div>
  <div class="flex items-center gap-3"><div class="flex items-center gap-1 text-sm">❤️ <span id="wishLeft" class="font-black">10</span></div><button id="voiceBtn" onclick="toggleVoice()" class="bg-[#222] px-3 py-1.5 rounded-full text-xs">🔊</button></div>
</div>

<div class="grid grid-cols-12 gap-3 max-w-[1400px] mx-auto mt-3 h-[calc(100vh-70px)]">
  <div class="col-span-12 lg:col-span-3 space-y-3 overflow-y-auto">
    <div class="glass rounded-[20px] p-4"><h3 class="font-black text-xs uppercase tracking-widest opacity-60">Daily Quests</h3>
      <div id="q1" class="mt-3 flex justify-between items-center bg-black/30 p-2.5 rounded-xl text-xs"><span>💬 Ask 3 doubts</span><span class="quest px-2 py-0.5 rounded-full bg-white/10">0/3</span></div>
      <div id="q2" class="mt-2 flex justify-between items-center bg-black/30 p-2.5 rounded-xl text-xs"><span>💻 Ask 1 code</span><span class="quest px-2 py-0.5 rounded-full bg-white/10">0/1</span></div>
      <div id="q3" class="mt-2 flex justify-between items-center bg-black/30 p-2.5 rounded-xl text-xs"><span>🔥 Keep streak</span><span class="quest px-2 py-0.5 rounded-full bg-green-500/20 text-green-400">DONE</span></div>
    </div>
    <div class="glass rounded-[20px] p-4"><h3 class="font-black text-xs">❤️ Lives</h3><div id="lampRow" class="grid grid-cols-5 gap-2 mt-3"></div><div class="mt-3 h-1.5 bg-black/50 rounded-full"><div id="wishBar" class="h-full bg-orange-400 transition-all" style="width:0%"></div></div><p class="text-[10px] mt-2 opacity-40">Refills in 24h • Pro = ∞ lives</p></div>
    <div class="glass rounded-[20px] p-4"><h3 class="font-black text-xs">🏆 Top Grinders</h3><div id="board" class="mt-3 space-y-2"></div></div>
  </div>

  <div class="col-span-12 lg:col-span-9 glass rounded-[24px] p-3 md:p-4 flex flex-col h-full">
    <div id="chat" class="flex-1 overflow-y-auto space-y-4 pr-1">
      <div class="flex gap-3"><div class="w-8 h-8 rounded-full bg-gradient-to-br from-orange-400 to-yellow-400 flex items-center justify-center">🧞</div><div class="bubble-ai p-4 rounded-[18px] max-w-[85%] text-[13.5px]">Yo aaka! Main Sparsh ka Genie 🔮<br><br>Har jawab pe <b class="text-orange-400">+12 XP</b> milega. Level badha, leaderboard phaad!<br><br><span class="text-[11px] opacity-60">Tip: Code puchhega toh dry run ke saath dunga 💻</span></div></div>
    </div>
    <div class="mt-3 flex gap-2 overflow-x-auto"><button onclick="quickAsk('Linked List code de dry run ke saath')" class="shrink-0 chip bg-white text-black px-3 py-2 rounded-full text-xs font-bold shimmer">💻 Linked List = Code + Visual</button><button onclick="quickAsk('Photosynthesis trick')" class="shrink-0 bg-[#1e1b2e] px-3 py-2 rounded-full text-xs">🌿 Photosynthesis hack</button><button onclick="quickAsk('Roast me savage')" class="shrink-0 bg-[#1e1b2e] px-3 py-2 rounded-full text-xs">🔥 Roast</button><button onclick="quickAsk('Ek joke suna')" class="shrink-0 bg-[#1e1b2e] px-3 py-2 rounded-full text-xs">😂</button></div>
    <div class="mt-3 bg-[#0f0e17] border border-white/10 rounded-full p-1.5 flex items-center gap-2"><input id="q" class="flex-1 bg-transparent px-4 py-2.5 outline-none text-[14px]" placeholder="Kya seekhna hai aaka? ✨" onkeypress="if(event.key==='Enter')ask()"><button onclick="ask()" class="bg-white text-black w-10 h-10 rounded-full font-black">→</button></div>
    <div class="mt-2 text-[10px] text-center opacity-30">People also ask: <span class="underline cursor-pointer" onclick="quickAsk('Binary Search easiest trick')">Binary Search trick?</span> • <span class="underline cursor-pointer" onclick="quickAsk('Mitochondria function')">Mitochondria kya hai?</span></div>
  </div>
</div>

<!-- 28 FEATURES ₹49 MODAL -->
<div id="payModal" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4" style="background:rgba(0,0,0,0.88); backdrop-filter:blur(18px)">
  <div class="glass rounded-[28px] p-6 max-w-[420px] w-full border border-orange-500/30 text-center flex flex-col max-h-[92vh]">
    <div class="w-16 h-16 mx-auto rounded-[18px] bg-gradient-to-br from-orange-400 to-yellow-400 flex items-center justify-center text-2xl">🧞‍♂️</div>
    <h2 class="mt-4 text-[22px] font-black leading-tight">Lives khatam! 🪔</h2>
    <p class="text-[12px] opacity-60 mt-1">FOMO: ₹49 offer ends in <span id="timer" class="text-orange-400 font-bold">23:59:59</span></p>
    <p class="text-[13px] opacity-70 mt-2">10 free wishes done. Pro pe 28 powers 🔓</p>
    <div class="mt-4 bg-black/50 rounded-[16px] p-3 text-left text-[11.5px] space-y-1.5 border border-white/5 overflow-y-auto max-h-[35vh]">
      <div>✅ Unlimited wishes • Voice full speed • Top boost</div>
      <div>✅ PDF Upload • Image Doubt • Code Execution</div>
      <div>✅ Dry Run Visualizer • Memory Retention • Personal Notes</div>
      <div>✅ Flashcards • Mock Tests • Trick Generator • Roast Pro</div>
      <div>✅ No Ads • Priority Speed • Doubt Chain • Formula Sheet</div>
      <div>✅ Chapter Wise • PYQ Solver • Code Optimizer • Error Finder</div>
      <div>✅ Concept Map • Voice Doubt • Share Chat • Streak Freeze</div>
      <div>✅ Dark Pro Theme • Sparsh Support + 6 more secret powers</div>
    </div>
    <button onclick="buyPro()" class="w-full mt-5 bg-white text-black font-black py-3.5 rounded-full shimmer">Unlock All 28 Powers - ₹49/month 🚀</button>
    <button onclick="closePay()" class="w-full mt-2 text-xs opacity-50 py-2">Abhi nahi</button>
  </div>
</div>

<script>
let voiceOn=true, synth=window.speechSynthesis, queue=[], isSpeaking=false;
let userId = localStorage.getItem('genie_userId') || 'user_'+Math.random().toString(36).substr(2,9);
localStorage.setItem('genie_userId', userId);
let stats = JSON.parse(localStorage.getItem('genie_stats') || '{"xp":0,"level":1,"wishes":0,"streak":3,"q1":0,"q2":0}');
let isDev = localStorage.getItem('isDev')==='true';
function lamps(){let row=document.getElementById('lampRow'); row.innerHTML=''; for(let i=0;i<10;i++){let used=i<stats.wishes&&!isDev; row.innerHTML+=`<div class="lamp ${used?'off':''} w-9 h-9 rounded-[12px] bg-gradient-to-br from-orange-400 to-yellow-300 flex items-center justify-center">${used?'💨':'🔥'}</div>`;}}
function save(){localStorage.setItem('genie_stats', JSON.stringify(stats)); render();}
function render(){
  document.getElementById('wishLeft').innerText=isDev?'∞':Math.max(0,10-stats.wishes);
  document.getElementById('lvlTop').innerText=stats.level;
  document.getElementById('wishBar').style.width=isDev?'100%':(stats.wishes*10)+'%';
  document.getElementById('xpBarTop').style.width=stats.xp+'%';
  document.getElementById('q1').querySelector('.quest').innerText=stats.q1+'/3'; if(stats.q1>=3) document.getElementById('q1').querySelector('.quest').classList.add('quest-done');
  lamps(); loadBoard();
}
async function loadBoard(){try{let r=await fetch('/leaderboard?uid='+userId); let d=await r.json(); let html=''; d.slice(0,5).forEach((u,i)=>{let isMe=u.id===userId; let m=i==0?'🥇':i==1?'🥈':i==2?'🥉':`#${i+1}`; html+=`<div class="flex justify-between bg-black/20 px-2 py-1.5 rounded-xl text-xs ${isMe?'border border-orange-500/30':''}"><span>${m} ${u.name} ${isMe?'(You)':''}</span><span class="font-bold">${u.xp} XP</span></div>`}); document.getElementById('board').innerHTML=html||'<p class="text-xs opacity-40">First grinder!</p>';}catch{}}
let c=0; document.getElementById('logo').addEventListener('click',()=>{c++; if(c>=5){isDev=!isDev; localStorage.setItem('isDev',isDev); alert(isDev?'DEV ON':'DEV OFF'); c=0; render();} setTimeout(()=>c=0,2000);});
function toggleVoice(){voiceOn=!voiceOn; document.getElementById('voiceBtn').innerText=voiceOn?'🔊':'🔇'; if(!voiceOn){synth.cancel(); queue=[]; isSpeaking=false;}}
function clean(t){return t.replace(/<[^>]*>/g,'').replace(/[*#_`~]/g,'').trim();}
function speakQueue(t){if(!voiceOn) return; let s=clean(t).match(/[^.!?]+[.!?]+|[\\s\\S]{1,140}(?=\\s|$)/g)||[clean(t)]; queue.push(...s); if(!isSpeaking) playNext();}
function playNext(){if(!queue.length){isSpeaking=false; return;} isSpeaking=true; let u=new SpeechSynthesisUtterance(queue.shift()); u.lang='hi-IN'; u.rate=1.05; u.onend=()=>playNext(); synth.speak(u);}
function closePay(){document.getElementById('payModal').classList.add('hidden');}
function buyPro(){alert("Pro ₹49! Razorpay yahan"); closePay();}
function quickAsk(t){document.getElementById('q').value=t; ask();}
function showXpPop(){let d=document.createElement('div'); d.className='xp-pop fixed top-1/2 left-1/2 text-2xl font-black text-yellow-300'; d.innerText='+12 XP'; document.body.appendChild(d); setTimeout(()=>d.remove(),1000);}
async function ask(){
  let input=document.getElementById('q'); let q=input.value.trim(); if(!q) return;
  if(!isDev && stats.wishes>=10){document.getElementById('payModal').classList.remove('hidden'); return;}
  let chat=document.getElementById('chat');
  chat.innerHTML+=`<div class="flex justify-end"><div class="bubble-user px-4 py-2.5 rounded-[16px] text-[13px]">${q}</div></div>`; input.value='';
  stats.wishes++; stats.q1=Math.min(3,stats.q1+1); if(q.toLowerCase().includes('code')||q.toLowerCase().includes('linked')||q.toLowerCase().includes('list')) stats.q2=1; stats.xp+=12; if(stats.xp>=100){stats.level++; stats.xp=0; chat.innerHTML+=`<div class="text-center text-xs py-2">🎉 LEVEL UP! You are now Level ${stats.level} 🚀</div>`;} save(); showXpPop();
  fetch('/update_xp',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({uid:userId, xp:(stats.level-1)*100+stats.xp, level:stats.level})});
  chat.innerHTML+=`<div id="typing" class="flex gap-2"><div class="w-8 h-8 rounded-full bg-[#222] flex items-center justify-center">🧞</div><div class="bubble-ai px-4 py-2 text-xs opacity-50">Genie soch raha hai...</div></div>`; chat.scrollTop=chat.scrollHeight;
  let res=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({q})}); let data=await res.json();
  document.getElementById('typing')?.remove();
  let id=Date.now(); chat.innerHTML+=`<div class="flex gap-2"><div class="w-8 h-8 rounded-full bg-gradient-to-br from-orange-400 to-yellow-400 flex items-center justify-center text-xs">🧞</div><div class="bubble-ai p-3 rounded-[16px] max-w-[85%] text-[13px] whitespace-pre-wrap"><span id="ans-${id}">${data.ans}</span><div class="mt-2 flex gap-2"><button onclick="speakQueue(document.getElementById('ans-${id}').innerText)" class="text-[10px] bg-white/10 px-2 py-1 rounded-full">🔊</button><button onclick="navigator.clipboard.writeText(document.getElementById('ans-${id}').innerText)" class="text-[10px] bg-white/10 px-2 py-1 rounded-full">📋</button></div></div></div>`;
  chat.scrollTop=chat.scrollHeight; speakQueue(data.ans);
}
// timer
let sec=86399; setInterval(()=>{sec--; let h=Math.floor(sec/3600), m=Math.floor((sec%3600)/60), s=sec%60; let el=document.getElementById('timer'); if(el) el.innerText=`${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;},1000);
render();
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
