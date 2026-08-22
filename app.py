from flask import Flask, request, jsonify, send_from_directory
import os
app = Flask(__name__)

def call_gemini(prompt):
    from google import genai
    client = genai.Client(api_key=os.getenv("GEMINI_KEY"))
    r = client.models.generate_content(model="gemini-3.6-flash", contents=prompt)
    return r.text

def get_prompt(mode, topic):
    return {
        "explain": f"Explain '{topic}' in Hinglish: 🔥 Definition, 🧱 5 Points, 💡 Example, 🧠 Trick.",
        "feynman": f"Explain '{topic}' like I'm 10 yrs old in Hinglish, chai/cricket example.",
        "code": f"For '{topic}' give C++ code + Dry Run table + Mistakes. Hinglish.",
        "interview": f"5 TCS/Infosys/Wipro interview Qs for '{topic}' with 1-line Hinglish answer.",
        "quiz": f"Create 5 MCQs on '{topic}' in JSON: [{{'q':'...','options':['a','b','c','d'],'ans':'a'}}] Only JSON.",
        "cheatsheet": f"CheatSheet for '{topic}' 250 words Hinglish."
    }.get(mode, f"Explain '{topic}' in Hinglish")

@app.route("/static/<path:f>")
def static_files(f): return send_from_directory("static", f)

@app.route("/")
def home():
    return """
<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>StudyGenie by Sparsh</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;700;900&display=swap" rel="stylesheet">
<style>
*{font-family:'Outfit',sans-serif;box-sizing:border-box}
body{margin:0;background:#08080a;color:#fff;padding:16px;background-image:radial-gradient(at 10% 20%, #ff3a0033 0, transparent 50%),radial-gradient(at 90% 80%, #7000ff33 0, transparent 50%)}
.wrap{max-width:1000px;margin:0 auto}
.topbar{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:10px}
.profile-left{display:flex;align-items:center;gap:12px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);border-radius:18px;padding:8px 14px 8px 8px;backdrop-filter:blur(12px)}
.profile-left img{width:56px;height:56px;border-radius:50%;object-fit:cover;border:2px solid #ff8a00;box-shadow:0 0 12px rgba(255,138,0,0.5)}
.profile-name{line-height:1.1}
.profile-name b{display:block;font-size:14px}
.profile-name span{font-size:11px;color:#999}
.header{flex:1;text-align:center}
.header h1{font-size:48px;font-weight:900;margin:0;background:linear-gradient(90deg,#fff,#ff8a00,#ff3a00);-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:-2px}
.sub{color:#777;letter-spacing:3px;font-size:10px;margin-top:4px}
.tabs{display:flex;gap:8px;overflow-x:auto;padding:10px 0}
.tab{white-space:nowrap;padding:10px 18px;border-radius:100px;background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.1);cursor:pointer;font-weight:700;font-size:13px}
.tab.active{background:#fff;color:#000}
.search{display:flex;gap:10px;background:rgba(255,255,255,0.08);padding:8px;border-radius:20px;border:1px solid rgba(255,255,255,0.12);margin:14px 0}
.search input{flex:1;background:transparent;border:none;padding:12px 18px;color:#fff;font-size:17px;outline:none}
.btn{padding:12px 24px;border-radius:14px;border:none;background:linear-gradient(135deg,#ff3a00,#ff8a00);color:#fff;font-weight:900;cursor:pointer}
.card{background:rgba(255,255,255,0.06);backdrop-filter:blur(16px);border:1px solid rgba(255,255,255,0.1);border-radius:24px;padding:22px;min-height:220px;white-space:pre-wrap;line-height:1.7}
.badge{font-size:10px;padding:5px 10px;border-radius:100px;background:#ff3a0026;border:1px solid #ff3a0050;color:#ff8a00;font-weight:800}
@media(max-width:700px){.topbar{flex-direction:column}.profile-left{width:100%;justify-content:center}.header h1{font-size:38px}}
</style></head><body>
<div class="wrap">

<div class="topbar">
  <div class="profile-left">
    <img src="/static/sparsh.jpg" onerror="this.src='https://i.pravatar.cc/150?u=sparsh'">
    <div class="profile-name">
      <b>Sparsh Singhal</b>
      <span>Builder • BTech • Educator ✔</span>
    </div>
  </div>

  <div class="header">
    <h1>StudyGenie 🧞</h1>
    <div class="sub">BY SPARSH SINGHAL • NOT CHATGPT, YOUR PADHAI GENIE</div>
  </div>

  <div style="width:170px"></div>
</div>

<div class="tabs" id="tabs">
<div class="tab active" data-m="explain">🧠 Explain</div><div class="tab" data-m="feynman">👶 Feynman 10yr</div><div class="tab" data-m="code">💻 Code + Dry Run</div><div class="tab" data-m="interview">🎯 Interview Qs</div><div class="tab" data-m="quiz">📝 Quiz</div><div class="tab" data-m="cheatsheet">📄 CheatSheet</div>
</div>

<div class="search"><input id="topic" placeholder="Topic: Arrays, Linked List, OOPS..."><button class="btn" onclick="run()">GO →</button></div>
<div id="out" class="card"><span class="badge">✨ READY</span>

Topic likh aur GO daba - ab teri photo ke saath site live hogi!
</div>

<div style="text-align:center;color:#444;font-size:10px;margin-top:22px;letter-spacing:2px">POWERED BY GEMINI 3.6 FLASH • PHASE 2 LIVE</div>
</div>

<script>
let mode='explain';
document.querySelectorAll('.tab').forEach(t=>{t.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));t.classList.add('active');mode=t.dataset.m;if(document.getElementById('topic').value)run()}})
async function run(){
 let topic=document.getElementById('topic').value.trim()||'Arrays';
 let out=document.getElementById('out');
 out.innerHTML='<span class="badge">🤖 SOCH RAHA HU...</span>\\n\\n'+topic+' ke liye '+mode+' bana raha hu...';
 try{let res=await fetch('/api/genie',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({topic,mode})});let data=await res.json();out.innerHTML='<span class="badge">🔥 '+mode.toUpperCase()+' • '+topic+'</span>\\n\\n'+data.reply}catch(e){out.innerHTML='Error: '+e}
}
document.getElementById('topic').addEventListener('keypress',e=>{if(e.key==='Enter')run()});
</script></body></html>
"""

@app.route("/api/genie", methods=["POST"])
def genie():
    d=request.get_json() or {}
    try:
        reply=call_gemini(get_prompt(d.get("mode","explain"), d.get("topic","OOPS")))
        return jsonify({"reply":reply})
    except Exception as e:
        return jsonify({"reply":f"Error: {str(e)}"})

@app.route("/health")
def h(): return "OK"
