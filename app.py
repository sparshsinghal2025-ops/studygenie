import os
from flask import Flask, jsonify, request
from flask_cors import CORS

# --- 10K Ready Redis ---
REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
redis_client = None
try:
    if REDIS_URL and REDIS_TOKEN:
        from upstash_redis import Redis
        redis_client = Redis(url=REDIS_URL, token=REDIS_TOKEN)
except: pass

app = Flask(__name__)
CORS(app)

# --- API ---
@app.route("/api/admin_users")
def admin_users():
    return jsonify({"redis": "ON" if redis_client else "OFF", "status": "LIVE - 10K READY"})

@app.route("/api/leaderboard")
def leaderboard():
    try:
        if not redis_client: return jsonify([])
        data = redis_client.zrange("studygenie:board", 0, 99, with_scores=True, rev=True)
        resp = jsonify([{"name": k, "score": int(v)} for k,v in data])
        resp.headers["Cache-Control"] = "s-maxage=5, stale-while-revalidate=60"
        return resp
    except: return jsonify([])

@app.route("/api/save-score", methods=["POST"])
def save_score():
    try:
        b = request.get_json()
        name, score = str(b.get("name","User"))[:15], int(b.get("score",0))
        if redis_client:
            redis_client.zadd("studygenie:board", {name: score}, gt=True)
            redis_client.zremrangebyrank("studygenie:board", 0, -101)
        return jsonify({"ok": True})
    except: return jsonify({"ok": False})

# --- FULL FRONTEND + DESIGN + SOUND + BOT IN ONE FILE ---
HTML = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>StudyGenie.ai</title>
<style>
body{margin:0;font-family:Inter,system-ui;background:#0f0f12;color:white;display:flex;justify-content:center;min-height:100vh}
.card{width:95%;max-width:480px;margin-top:30px;background:#1a1a20;border:1px solid #2a2a33;border-radius:24px;padding:24px;box-shadow:0 20px 60px rgba(0,0,0,.5)}
h1{font-size:28px;margin:0 0 10px}.sub{color:#9a9ab0;font-size:14px;margin-bottom:20px}
.btn{width:100%;padding:16px;border-radius:14px;border:0;background:white;color:black;font-weight:700;font-size:16px;cursor:pointer;transition:.2s}
.btn:active{transform:scale(.97)}.opt{padding:14px;border-radius:12px;background:#252530;margin:8px 0;cursor:pointer;border:1px solid #333}
.opt.correct{background:#1e3a2a;border-color:#2f9e44}.opt.wrong{background:#3a1e1e;border-color:#e03131}
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:15px}
.score{font-weight:800;color:#ffd43b} #leaderboard{margin-top:20px;max-height:200px;overflow:auto}
.row{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #222;font-size:14px}
</style>
</head>
<body>
<div class="card">
  <div class="top"><h1>StudyGenie 🧞‍♂️</h1><div class="score" id="score">Score: 0</div></div>
  <div class="sub">10K users ready • Live leaderboard • Sound ON</div>
  <div id="quiz"></div>
  <button class="btn" id="next" style="display:none;margin-top:15px" onclick="nextQ()">Next Question →</button>
  <div id="leaderboard"><b>🏆 Live Top 100</b><div id="board">Loading...</div></div>
  <div style="margin-top:15px;display:flex;gap:10px">
    <input id="name" placeholder="Your name" style="flex:1;padding:12px;border-radius:10px;border:1px solid #333;background:#111;color:white">
    <button class="btn" style="width:auto;padding:12px 20px" onclick="saveScore()">Save</button>
  </div>
</div>
<script>
const questions=[
{q:"What does CPU stand for?",o:["Central Process Unit","Central Processing Unit","Computer Personal Unit"],a:1},
{q:"Python is?",o:["Compiled","Interpreted","Both"],a:1},
{q:"Fastest way to store data for 10k users?",o:["MySQL","Upstash Redis","Local File"],a:1},
{q:"Vercel is best for?",o:["Frontend Hosting","Heavy ML","Mining"],a:0}
];
let idx=0, score=0;
const quizEl=document.getElementById('quiz'), scoreEl=document.getElementById('score');

// --- SOUND EFFECTS (No mp3 needed) ---
const ctx=new (window.AudioContext||window.webkitAudioContext)();
function playSound(type){
  const o=ctx.createOscillator(), g=ctx.createGain();
  o.connect(g); g.connect(ctx.destination);
  if(type=='correct'){o.frequency.value=880; g.gain.setValueAtTime(.3,ctx.currentTime); o.start(); o.stop(ctx.currentTime+.15)}
  if(type=='wrong'){o.frequency.value=150; g.gain.setValueAtTime(.3,ctx.currentTime); o.start(); o.stop(ctx.currentTime+.25)}
  if(type=='click'){o.frequency.value=600; g.gain.setValueAtTime(.1,ctx.currentTime); o.start(); o.stop(ctx.currentTime+.07)}
}

function render(){
  const q=questions[idx];
  quizEl.innerHTML=`<h3>${idx+1}. ${q.q}</h3>`+q.o.map((op,i)=>`<div class="opt" onclick="check(${i})">${op}</div>`).join('');
  document.getElementById('next').style.display='none';
}
function check(i){
  playSound(i==questions[idx].a?'correct':'wrong');
  const opts=document.querySelectorAll('.opt');
  opts.forEach((el,ci)=>{
    if(ci==questions[idx].a) el.classList.add('correct');
    else if(ci==i) el.classList.add('wrong');
  });
  if(i==questions[idx].a) score+=100;
  scoreEl.innerText='Score: '+score;
  document.getElementById('next').style.display='block';
}
function nextQ(){
  playSound('click'); idx++;
  if(idx<questions.length) render();
  else quizEl.innerHTML=`<h2>Done! 🎉 Final Score: ${score}</h2><p>Save your score to leaderboard</p>`;
}

async function loadBoard(){
  try{
    const r=await fetch('/api/leaderboard'); const d=await r.json();
    document.getElementById('board').innerHTML=d.length?d.map((x,i)=>`<div class="row"><span>${i+1}. ${x.name}</span><b>${x.score}</b></div>`).join(''):'No scores yet';
  }catch{}
}
async function saveScore(){
  const name=document.getElementById('name').value||'Anon';
  await fetch('/api/save-score',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,score})});
  playSound('correct'); loadBoard();
}
render(); loadBoard();
setInterval(loadBoard,5000); // Live update every 5 sec
</script>
</body>
</html>
"""

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve(path):
    return HTML

if __name__ == "__main__":
    app.run()
