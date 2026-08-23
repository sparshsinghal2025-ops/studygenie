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
<style>body{background:#1e1b4b;color:white}.glass{background:rgba(255,255,255,0.08);backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,0.1)}.chip{cursor:pointer}.chip:hover{transform:scale(1.05);background:rgba(249,115,22,0.3)}</style>
</head><body class="p-3">
<div class="flex justify-between items-center mb-3">
  <div class="flex items-center gap-3">
    <img src="/sparsh.jpg" class="w-14 h-14 rounded-full border-2 border-orange-500 object-cover">
    <div><h1 class="text-xl font-black">StudyGenie <span class="text-orange-400">by Sparsh</span></h1><p class="text-xs opacity-70">Bolne wala Genie</p></div>
  </div>
  <button id="voiceBtn" onclick="toggleVoice()" class="glass px-3 py-1 rounded-full text-xs font-bold bg-green-500/20 border border-green-500">🔊 Voice: ON</button>
</div>
<div class="grid grid-cols-1 md:grid-cols-4 gap-3">
  <div class="md:col-span-3 glass rounded-2xl p-3 flex flex-col min-h-[70vh]">
    <div id="chat" class="flex-1 space-y-3 overflow-y-auto"><div class="bg-white/15 p-3 rounded-2xl max-w-[90%]">Hukm mere aaka! 🧞 Mai Sparsh ka Genie hu, bolo kya chahiye? 😏</div></div>
    <div class="flex gap-2 mt-3 flex-wrap">
      <span class="chip glass px-3 py-1 rounded-full text-xs" onclick="quickAsk(this)">📚 Linked List samjha</span>
      <span class="chip glass px-3 py-1 rounded-full text-xs" onclick="quickAsk(this)">😂 Joke suna</span>
      <span class="chip glass px-3 py-1 rounded-full text-xs" onclick="quickAsk(this)">🔥 Roast kar</span>
    </div>
    <div class="mt-3 flex gap-2"><input id="q" class="flex-1 glass rounded-full px-4 py-3 outline-none text-sm" placeholder="Bol aaka..." onkeypress="if(event.key==='Enter')ask()"><button onclick="ask()" class="bg-orange-500 px-6 py-3 rounded-full font-black">GO</button></div>
  </div>
  <div class="space-y-3"><div class="glass p-4 rounded-2xl"><h3 class="font-bold">Wishes <span class="text-orange-400">Unlimited</span></h3></div></div>
</div>
<script>
let voiceOn=true; let synth=window.speechSynthesis;
function toggleVoice(){voiceOn=!voiceOn; document.getElementById('voiceBtn').innerHTML=voiceOn?'🔊 Voice: ON':'🔇 Voice: OFF'; if(!voiceOn) synth.cancel();}
function cleanForSpeech(text){
  return text
   .replace(/<[^>]*>/g,'')
   .replace(/[*#_`~]/g,'')
   .replace(/[\\u{1F600}-\\u{1F64F}\\u{1F300}-\\u{1F5FF}\\u{1F680}-\\u{1F6FF}\\u{2600}-\\u{26FF}\\u{2700}-\\u{27BF}\\u{1F900}-\\u{1F9FF}\\u{1FA70}-\\u{1FAFF}]/gu,'')
   .replace(/:[a-z_]+:/g,'')
   .replace(/\\s+/g,' ').trim().slice(0,400);
}
function speak(text){
  if(!voiceOn) return; synth.cancel();
  let clean = cleanForSpeech(text); if(!clean) return;
  let utter = new SpeechSynthesisUtterance(clean); utter.lang='hi-IN'; utter.rate=1.05;
  let voices=synth.getVoices(); let v=voices.find(x=>x.lang.includes('hi'))||voices.find(x=>x.lang.includes('en-IN'))||voices[0]; if(v) utter.voice=v;
  synth.speak(utter);
}
function quickAsk(el){document.getElementById('q').value=el.innerText.replace(/^[📚😂🔥🧠💡]\\s*/,''); ask();}
async function ask(){
  let input=document.getElementById('q'); let q=input.value.trim(); if(!q) return;
  let chat=document.getElementById('chat'); chat.innerHTML+=`<div class="bg-orange-500 p-3 rounded-2xl max-w-[85%] ml-auto text-sm">${q}</div>`; input.value='';
  chat.innerHTML+=`<div id="typing" class="bg-white/10 p-3 rounded-2xl max-w-[50%] text-xs">Genie soch raha hai... 🧞💭</div>`;
  let res=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({q})}); let data=await res.json();
  document.getElementById('typing')?.remove();
  let id=Date.now(); chat.innerHTML+=`<div class="bg-white/15 p-3 rounded-2xl max-w-[90%] text-sm whitespace-pre-wrap"><span id="ans-${id}">${data.ans}</span><br><button onclick="speak(document.getElementById('ans-${id}').innerText)" class="mt-2 text-xs glass px-2 py-1 rounded-full">🔊 Suna de</button></div>`;
  chat.scrollTop=chat.scrollHeight; speak(data.ans);
}
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
    if not client: return jsonify({"ans":"API Key missing"})
    try:
        prompt=f"You are StudyGenie by Sparsh Singhal, funny Gen-Z Genie. Reply in Hinglish with emojis for display, but keep language clean for voice. Max 150 words. Add humor, keep interactive, end with a question. User: {q}"
        response=client.models.generate_content(model="gemini-3.6-flash", contents=prompt)
        return jsonify({"ans":response.text})
    except Exception as e: return jsonify({"ans":f"Error 😅: {str(e)}"})
if __name__=="__main__": app.run()
