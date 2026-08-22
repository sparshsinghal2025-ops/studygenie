from flask import Flask, request, jsonify
import os, json
app = Flask(__name__)

def call_gemini(prompt):
    from google import genai
    client = genai.Client(api_key=os.getenv("GEMINI_KEY"))
    r = client.models.generate_content(model="gemini-3.6-flash", contents=prompt)
    return r.text

def get_prompt(mode, topic):
    prompts = {
        "explain": f"Explain '{topic}' in Hinglish with this EXACT format: 🔥 Definition (1 line), 🧱 5 Points (with emoji), 💡 Real Example (college life), 🧠 Trick to Remember. Tone GenZ friendly.",
        "feynman": f"Explain '{topic}' like I'm 10 years old in Hinglish. Use only simple daily life example like chai, cricket, momos. No jargon.",
        "code": f"For '{topic}' give: 1. Simplest C++ code 2. Step-by-step Dry Run with table like i=0, arr[0]=... 3. Common mistakes students make. In Hinglish comments.",
        "interview": f"Give 5 most asked Interview Questions for '{topic}' for TCS/Infosys/Wipro. Give 1-line Hinglish answer for each. Mark 🔥 for most important.",
        "quiz": f"Create 5 MCQs on '{topic}' in JSON format: [{{'q':'...','options':['a','b','c','d'],'ans':'a'}}]. No extra text, only valid JSON. Language Hinglish.",
        "cheatsheet": f"Create a One-Page CheatSheet for '{topic}' for last night revision. Use emojis, tables, formulas, very short points. Max 250 words. Hinglish."
    }
    return prompts.get(mode, prompts["explain"])

@app.route("/")
def home():
    return """
<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>StudyGenie - Not Just AI, Your Padhai Partner</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;700;900&display=swap" rel="stylesheet">
<style>
*{font-family:'Outfit',sans-serif;box-sizing:border-box}
body{margin:0;background:#050505;color:#fff;min-height:100vh;padding:16px;background-image:radial-gradient(at 10% 10%, #ff3a0033 0, transparent 50%),radial-gradient(at 90% 90%, #7000ff33 0, transparent 50%)}
.wrap{max-width:900px;margin:0 auto}
.header{text-align:center;padding:20px 0}
.header h1{font-size:56px;font-weight:900;margin:0;background:linear-gradient(90deg,#fff,#ff8a00,#ff3a00);-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:-2px}
.tabs{display:flex;gap:8px;overflow-x:auto;padding:10px 0;scrollbar-width:none}
.tab{white-space:nowrap;padding:10px 18px;border-radius:100px;background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.1);cursor:pointer;font-weight:700;font-size:13px;transition:.2s}
.tab.active{background:#fff;color:#000;transform:scale(1.05)}
.search{margin:16px 0;display:flex;gap:10px;background:rgba(255,255,255,0.08);padding:8px;border-radius:20px;border:1px solid rgba(255,255,255,0.12)}
.search input{flex:1;background:transparent;border:none;padding:12px 18px;color:#fff;font-size:17px;outline:none}
.btn{padding:12px 22px;border-radius:14px;border:none;background:linear-gradient(135deg,#ff3a00,#ff8a00);color:#fff;font-weight:900;cursor:pointer}
.card{background:rgba(255,255,255,0.06);backdrop-filter:blur(16px);border:1px solid rgba(255,255,255,0.1);border-radius:24px;padding:22px;min-height:300px;white-space:pre-wrap;line-height:1.7;font-size:14.5px}
.badge{font-size:11px;padding:5px 10px;border-radius:100px;background:#ff3a001a;border:1px solid #ff3a004d;color:#ff8a00;font-weight:800;letter-spacing:1px}
.quiz-opt{display:block;width:100%;text-align:left;padding:12px 16px;margin:8px 0;border-radius:12px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);color:#fff;cursor:pointer}
.quiz-opt.correct{background:#00ff8822;border-color:#00ff88}.quiz-opt.wrong{background:#ff003322;border-color:#ff0033}
.footer{text-align:center;color:#666;font-size:11px;margin-top:24px;letter-spacing:2px}
</style></head><body>
<div class="wrap">
<div class="header"><h1>StudyGenie 🔥</h1><div style="color:#777;letter-spacing:4px;font-size:12px;margin-top:6px">BY SPARSH SINGHAL • NOT CHATGPT, YOUR PADHAI GENIE</div></div>

<div class="tabs" id="tabs">
<div class="tab active" data-m="explain">🧠 Explain</div>
<div class="tab" data-m="feynman">👶 Feynman 10yr</div>
<div class="tab" data-m="code">💻 Code + Dry Run</div>
<div class="tab" data-m="interview">🎯 Interview Qs</div>
<div class="tab" data-m="quiz">📝 Instant Quiz</div>
<div class="tab" data-m="cheatsheet">📄 CheatSheet</div>
</div>

<div class="search">
<input id="topic" placeholder="Topic: e.g. Linked List, OOPS, DBMS, OS Deadlock...">
<button class="btn" onclick="run()">GO →</button>
</div>

<div id="out" class="card"><span class="badge">✨ WHY DIFFERENT FROM CHATGPT?</span>
ChatGPT = Generic answer
StudyGenie =

✓ Hinglish + Desi Examples (chai, cricket)
✓ Code ka Dry-Run Table (interview me kaam aayega)
✓ Direct Interview Questions (TCS/Infosys pattern)
✓ 5-sec Quiz with Score
✓ Exam wali CheatSheet

Topic likh ke upar se mode select kar - dekh jadoo!
</div>
<div class="footer">POWERED BY GEMINI 3.6 FLASH • FREE FOREVER • PHASE 2 LIVE</div>
</div>

<script>
let mode='explain';
document.querySelectorAll('.tab').forEach(t=>{
 t.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));t.classList.add('active');mode=t.dataset.m;run()}
})
async function run(){
 let topic=document.getElementById('topic').value.trim();
 if(!topic){topic='OOPS';}
 let out=document.getElementById('out');
 out.innerHTML='<span class="badge">🤖 GENIE SOCH RAHA HAI...</span>\\n\\n'+mode.toUpperCase()+' mode me "'+topic+'" ke liye best notes bana raha hu... 3 sec...';
 try{
  let res=await fetch('/api/genie',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({topic,mode})});
  let data=await res.json();
  if(mode==='quiz'){
   try{
    let qs=JSON.parse(data.reply.replace(/```json|```/g,''));
    let html='<span class="badge">📝 QUIZ - '+topic+'</span>\\n\\n';
    qs.forEach((q,i)=>{html+=`<b>Q${i+1}. ${q.q}</b>\\n`; q.options.forEach(o=>{html+=`<button class="quiz-opt" onclick="this.classList.add(this.textContent.trim().startsWith(q.ans)?'correct':'wrong')">${o}</button>`}); html+='\\n'});
    out.innerHTML=html; return;
   }catch(e){}
  }
  out.innerHTML='<span class="badge">🔥 '+mode.toUpperCase()+' - '+topic+'</span>\\n\\n'+data.reply;
  window.scrollTo({top:400,behavior:'smooth'});
 }catch(e){out.innerHTML='Error: '+e}
}
document.getElementById('topic').addEventListener('keypress',e=>{if(e.key==='Enter')run()});
</script></body></html>
"""

@app.route("/api/genie", methods=["POST"])
def genie():
    d = request.get_json() or {}
    topic = d.get("topic","OOPS")
    mode = d.get("mode","explain")
    try:
        reply = call_gemini(get_prompt(mode, topic))
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"reply": f"Error: {str(e)}"})

@app.route("/health")
def h(): return "OK"
