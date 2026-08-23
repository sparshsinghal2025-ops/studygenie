import os
from flask import Flask, request, jsonify, send_from_directory, render_template_string
from google import genai

app = Flask(__name__)
API_KEY = os.environ.get("GOOGLE_API_KEY", "")
client = genai.Client(api_key=API_KEY) if API_KEY else None

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
.chip{cursor:pointer; transition: all 0.2s}.chip:hover{transform:translateY(-2px); background: rgba(255,122,24,0.25); border-color: #ff7a18}
#chat::-webkit-scrollbar{width:5px} #chat::-webkit-scrollbar-thumb{background:#ff7a18; border-radius:10px}
.pulse-dot{animation:pulse 2s infinite} @keyframes pulse{0%,100%{opacity:1} 50%{opacity:0.5}}
</style>
</head>
<body class="p-3 md:p-5">
<!-- Header Premium -->
<div class="flex justify-between items-center glass rounded-2xl px-4 py-3 mb-4">
  <div class="flex items-center gap-3">
    <img src="/sparsh.jpg" class="w-12 h-12 md:w-14 md:h-14 rounded-full border-2 border-orange-500 object-cover shadow-lg">
    <div>
      <h1 class="text-lg md:text-2xl font-black tracking-tight">StudyGenie <span class="text-orange-400">by Sparsh</span></h1>
      <p class="text-[11px] md:text-xs opacity-70 flex items-center gap-1"><span class="w-2 h-2 bg-green-400 rounded-full pulse-dot inline-block"></span>Bolne wala Genie • Live</p>
    </div>
  </div>
  <div class="flex gap-2 items-center">
    <button id="voiceBtn" onclick="toggleVoice()" class="px-3 md:px-4 py-1.5 rounded-full text-xs font-bold bg-green-500/20 border border-green-500 hover:bg-green-500/30">🔊 Voice: ON</button>
    <span class="hidden md:block glass px-3 py-1 rounded-full text-xs">🔥 1 streak</span>
  </div>
</div>

<div class="grid grid-cols-1 lg:grid-cols-4 gap-4">
  <div class="lg:col-span-3 glass rounded-[24px] p-3 md:p-4 flex flex-col min-h-[75vh]">
    <div id="chat" class="flex-1 space-y-4 overflow-y-auto pr-1 max-h-[60vh] md:max-h-none">
      <div class="bubble-ai p-4 rounded-2xl rounded-bl-none max-w-[92%] text-sm leading-relaxed">Hukm mere aaka! 🧞 <b>Mai Sparsh ka Genie hu!</b> Ab mai premium dikhta bhi hu aur rukta bhi nahi! 😎<br><span class="text-xs opacity-60">Pucho kuch bhi, mai pura bolke samjhaunga.</span></div>
    </div>
    <div class="flex gap-2 mt-4 flex-wrap">
      <span class="chip glass px-3 py-1.5 rounded-full text-xs border border-white/10" onclick="quickAsk('Linked List samjha de masti me')">📚 Linked List</span>
      <span class="chip glass px-3 py-1.5 rounded-full text-xs border border-white/10" onclick="quickAsk('photosynthesis samjhao easy me')">🌿 Photosynthesis</span>
      <span class="chip glass px-3 py-1.5 rounded-full text-xs border border-white/10" onclick="quickAsk('Ek joke suna Genie style me')">😂 Joke</span>
      <span class="chip glass px-3 py-1.5 rounded-full text-xs border border-white/10" onclick="quickAsk('Mera roast kar de')">🔥 Roast</span>
      <span class="chip glass px-3 py-1.5 rounded-full text-xs border border-white/10" onclick="quickAsk('Quiz puch le')">🧠 Quiz</span>
    </div>
    <div class="mt-4 flex gap-2 items-center glass rounded-full p-1.5">
      <input id="q" class="flex-1 bg-transparent px-4 py-2 outline-none text-sm placeholder-white/40" placeholder="Bol aaka kya chahiye..." onkeypress="if(event.key==='Enter')ask()">
      <button onclick="ask()" class="bg-gradient-to-r from-orange-500 to-orange-600 hover:from-orange-600 hover:to-orange-700 px-6 md:px-8 py-2.5 rounded-full font-black text-sm shadow-lg">GO</button>
    </div>
    <div class="mt-3 flex items-center gap-2"><div class="flex-1 bg-black/30 h-2 rounded-full"><div class="bg-gradient-to-r from-yellow-300 to-orange-400 h-2 rounded-full" style="width:84%"></div></div><span class="text-[11px] opacity-70">84 XP • Level 1</span></div>
  </div>

  <div class="space-y-3">
    <div class="glass p-4 rounded-2xl"><h3 class="font-black text-sm">Wishes <span class="text-orange-400">Unlimited</span> <span class="text-[8px] border border-orange-400 px-2 py-0.5 rounded-full">DEV</span></h3><div class="h-1.5 bg-gradient-to-r from-orange-500 to-yellow-400 mt-3 rounded-full"></div><p class="text-[11px] mt-2 opacity-50">Only you is grinding 🔥</p></div>
    <div class="glass p-4 rounded-2xl"><p class="font-bold text-sm">🔋 Battery</p><p class="text-xs opacity-60 mt-1">Genie full charged hai aaka!</p></div>
    <div class="glass p-4 rounded-2xl"><p class="font-bold text-sm">🏆 Leaderboard #1</p><div class="flex items-center gap-2 mt-2"><img src="/sparsh.jpg" class="w-7 h-7 rounded-full"><p class="text-xs">You - 84 XP</p></div></div>
    <div class="glass p-3 rounded-2xl text-[11px] opacity-60">💡 <b>Pro Tip:</b> Voice ON rakho toh Genie pura lecture bolke dega bina ruke.</div>
  </div>
</div>

<script>
let voiceOn=true; let synth=window.speechSynthesis; let queue=[]; let isSpeaking=false;
function toggleVoice(){voiceOn=!voiceOn; document.getElementById('voiceBtn').innerHTML=voiceOn?'🔊 Voice: ON':'🔇 Voice: OFF'; document.getElementById('voiceBtn').className=voiceOn?'px-3 md:px-4 py-1.5 rounded-full text-xs font-bold bg-green-500/20 border border-green-500':'px-3 md:px-4 py-1.5 rounded-full text-xs font-bold bg-red-500/20 border border-red-500'; if(!voiceOn){synth.cancel(); queue=[]; isSpeaking=false;} else {speakQueue("Voice on aaka! Ab mai beech me nahi rukunga!");}}
function cleanForSpeech(t){return t.replace(/<[^>]*>/g,'').replace(/[*#_`~]/g,'').replace(/[\\u{1F600}-\\u{1F64F}\\u{1F300}-\\u{1F5FF}\\u{1F680}-\\u{1F6FF}\\u{2600}-\\u{26FF}\\u{2700}-\\u{27BF}\\u{1F900}-\\u{1F9FF}\\u{1FA70}-\\u{1FAFF}\\u{1F1E6}-\\u{1F1FF}]/gu,'').replace(/https?:\\/\\S+/g,'').replace(/\\s+/g,' ').trim();}
function speakQueue(fullText){
  if(!voiceOn) return; let clean=cleanForSpeech(fullText); if(!clean) return;
  // break into sentences ~150 chars
  let sentences=clean.match(/[^.!?]+[.!?]+|[\\s\\S]{1,140}(?=\\s|$)/g)||[clean];
  queue.push(...sentences); if(!isSpeaking) playNext();
}
function playNext(){
  if(queue.length==0){isSpeaking=false; return;} isSpeaking=true;
  let text=queue.shift(); let utter=new SpeechSynthesisUtterance(text); utter.lang='hi-IN'; utter.rate=1.02; utter.pitch=1;
  let voices=synth.getVoices(); let v=voices.find(x=>x.lang.includes('hi'))||voices.find(x=>x.lang.includes('en-IN'))||voices[0]; if(v) utter.voice=v;
  utter.onend=()=>{playNext();}; utter.onerror=()=>{playNext();}; synth.speak(utter);
}
function quickAsk(t){document.getElementById('q').value=t; ask();}
async function ask(){
  let input=document.getElementById('q'); let q=input.value.trim(); if(!q) return;
  let chat=document.getElementById('chat'); chat.innerHTML+=`<div class="bubble-user p-3 px-4 rounded-2xl rounded-br-none max-w-[85%] ml-auto text-sm font-medium">${q}</div>`; input.value='';
  chat.innerHTML+=`<div id="typing" class="bubble-ai p-3 rounded-2xl max-w-[40%] text-xs opacity-70 flex items-center gap-2"><span class="w-2 h-2 bg-orange-400 rounded-full animate-bounce"></span> Genie soch raha hai...</div>`; chat.scrollTop=chat.scrollHeight;
  let res=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({q})}); let data=await res.json();
  document.getElementById('typing')?.remove();
  let id=Date.now(); chat.innerHTML+=`<div class="bubble-ai p-4 rounded-2xl rounded-bl-none max-w-[92%] text-[13px] leading-relaxed whitespace-pre-wrap"><span id="ans-${id}">${data.ans}</span><div class="mt-3 flex gap-2"><button onclick="speakQueue(document.getElementById('ans-${id}').innerText)" class="text-[11px] glass px-3 py-1 rounded-full hover:bg-white/20">🔊 Pura suna de</button><button onclick="navigator.clipboard.writeText(document.getElementById('ans-${id}').innerText)" class="text-[11px] glass px-3 py-1 rounded-full hover:bg-white/20">📋 Copy</button></div></div>`;
  chat.scrollTop=chat.scrollHeight; speakQueue(data.ans);
}
window.speechSynthesis.onvoiceschanged=()=>{speechSynthesis.getVoices();}
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
@app.route("/ask", methods=["POST"])
def ask_gemini():
    q=request.json.get("q","")
    if not client: return jsonify({"ans":"API Key missing, Vercel me GOOGLE_API_KEY add kar aaka!"})
    try:
        prompt=f"You are StudyGenie by Sparsh Singhal. You are premium, funny, Gen-Z Genie. Reply in Hinglish with emojis for display. Keep answer crisp (max 180 words), engaging, use bullet points, examples. Always end with interactive question. User: {q}"
        resp=client.models.generate_content(model="gemini-3.6-flash", contents=prompt)
        return jsonify({"ans":resp.text})
    except Exception as e: return jsonify({"ans":f"Error 😅: {str(e)}"})
if __name__=="__main__": app.run()
