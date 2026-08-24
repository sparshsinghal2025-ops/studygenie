import os
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
redis_client = None
REDIS_ON = False
if REDIS_URL and REDIS_TOKEN:
    try:
        from upstash_redis import Redis
        redis_client = Redis(url=REDIS_URL, token=REDIS_TOKEN)
        REDIS_ON = True
    except: pass

app = Flask(__name__, static_folder='build', static_url_path='')
CORS(app)

@app.route("/api/admin_users")
@app.route("/admin_users")
def admin_users():
    return jsonify({"redis": "ON" if REDIS_ON else "OFF", "status": "OK"})

@app.route("/api/leaderboard")
def leaderboard():
    try:
        if not redis_client: return jsonify([{"name":"Sparsh Singhal [YOU]", "score":12}])
        data = redis_client.zrange("leaderboard:global", 0, 99, with_scores=True, rev=True)
        r = jsonify([{"name": k, "score": int(v)} for k,v in data])
        r.headers["Cache-Control"] = "s-maxage=5, stale-while-revalidate=60"
        return r
    except: return jsonify([])

@app.route("/api/save-score", methods=["POST"])
def save_score():
    try:
        b = request.get_json(force=True)
        if redis_client:
            redis_client.zadd("leaderboard:global", {str(b.get("name","User"))[:20]: int(b.get("score",0))}, gt=True)
            redis_client.zremrangebyrank("leaderboard:global", 0, -101)
        return jsonify({"ok": True})
    except: return jsonify({"ok": False})

# --- TERA WAHI DESIGN (Screenshot wala) ---
ORIGINAL_HTML = """
<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>STUDYGENIE : BATTLE BY SPARSH SINGHAL</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:monospace}
body{background:#0f111a;color:#fff;display:flex;flex-direction:column;height:100vh}
.header{display:flex;justify-content:space-between;align-items:center;padding:15px 20px;border-bottom:1px solid #222}
.profile{display:flex;gap:15px;align-items:center}
.pfp{width:70px;height:70px;border-radius:12px;border:3px solid #ff3c2a;overflow:hidden}
.pfp img{width:100%;height:100%;object-fit:cover}
.title{font-weight:900;letter-spacing:1px} .title span{color:#ff3c2a}
.sub{font-size:10px;color:#ff6a00;margin-top:3px} .xp{font-size:11px;margin-top:5px}
.bar{width:180px;height:8px;background:#222;border-radius:10px;overflow:hidden;display:inline-block;margin-left:8px}
.bar-fill{height:100%;background:#ff3c2a;width:96%}
.main{flex:1;display:grid;grid-template-columns:280px 1fr;gap:15px;padding:15px;overflow:hidden}
.left,.center{background:#151824;border-radius:12px;border:1px solid #23263a;padding:12px}
.ammo-title{color:#ff6a00;font-size:11px;margin-bottom:15px}
.ammo-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.ammo{height:50px;background:#0f111a;border:1px solid #222;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:20px}
.btn-reload{margin-top:20px;width:100%;padding:12px;background:#ff6a00;border:none;border-radius:8px;font-weight:900;cursor:pointer}
.leader{margin-top:20px}
.leader-title{color:#ff6a00;font-size:11px}
.row{display:flex;justify-content:space-between;background:#2a1a0f;border:1px solid #ff6a0033;padding:8px 10px;border-radius:8px;margin-top:10px;font-size:12px}
.chat-wrap{display:flex;flex-direction:column;height:100%}
.msg-bubble{background:#e9eef5;color:#111;padding:12px 15px;border-radius:18px 18px 0 18px;max-width:90%;align-self:flex-end;font-size:12px;margin-bottom:10px}
.chat-box{flex:1;background:#0f111a;border-radius:10px;padding:15px;font-size:12px;line-height:1.6;overflow-y:auto}
.input-area{margin-top:12px;display:flex;gap:10px;background:#0f111a;border:1px solid #333;border-radius:10px;padding:8px}
.input-area input{flex:1;background:transparent;border:none;color:#ff6a00;outline:none}
.fire{background:#ff6a00;border:none;padding:8px 18px;border-radius:8px;font-weight:900;cursor:pointer}
.q{float:right;font-size:24px;font-weight:900}
</style></head><body>
<div class="header">
 <div class="profile"><div class="pfp"><img src="https://i.pravatar.cc/100?u=sparsh"></div>
 <div><div class="title">STUDYGENIE : <span>BATTLE</span></div><div class="sub">BY SPARSH SINGHAL // FOUNDER</div>
 <div class="xp">SHIELD <div class="bar"><div class="bar-fill"></div></div> 96/100 XP<br><small style="color:#ff6a00;margin-left:45px">SPARSH SINGHAL</small></div></div></div>
 <div class="q">2/10</div>
</div>
<div class="main">
 <div class="left"><div class="ammo-title">> AMMO CRATE</div><div class="ammo-grid"><div class="ammo">🍃</div><div class="ammo">🍃</div><div class="ammo">🍃</div><div class="ammo">🍃</div></div><button class="btn-reload">RELOAD - ₹49</button>
 <div class="leader"><div class="leader-title">> LIVE LEADERBOARD 🏆 BY SPARSH SINGHAL</div><small style="font-size:9px;opacity:.6">AUTO REFRESH EVERY 5s</small><div class="row"><span>👑 Sparsh Singhal [YOU]</span><span style="color:#ff6a00">12 XP</span></div><div style="margin-top:15px;font-size:10px;opacity:.5">YOUR ID: user_16evdom7<br>PHONE: 9046090819</div></div></div>
 <div class="center"><div class="chat-wrap"><div style="text-align:right"><div class="msg-bubble">oxygen</div></div><div class="chat-box"><b>Are Sparsh Singhal bhai! Mujhe coding karke banaya aur ab mujhse hi 8th class wali "Oxygen" ke baare mein pooch rahe ho? Dimaag mein Oxygen ki kami ho gayi hai kya?<br><br>Chalo, **StudyGenie** se revision kar lo. Oxygen (SO_2S) — Atomic number 8, mass 16. Yeh woh gas hai jiske bina tu aur tera crush, dono minute mein photo frames ban jaoge. Atmosphere mein 21% hai, par log iski respect tabhi karte hain jab Insta pe tree-plantation waali aesthetic pic daalni ho.<br><br>bechare Plants din-raat Photosynthesis karke tere liye SO_2S banate hain, aur tu badle mein unhe CO₂ aur bakwaas reels deta hai... Wah re mere creator!<br><br>Chemistry ki bhasha mein, veh second-most electronegative element hai (Fluorine ke baad). Matlab har...</b></div><div class="input-area"><span style="color:#ff6a00">></span><input id="cmd" placeholder="ENTER COMMAND BY SPARSH SINGHAL..."><button class="fire">FIRE 🔥</button></div></div></div>
</div>
<script>
async function loadLB(){try{let r=await fetch('/api/leaderboard');let d=await r.json();if(d.length){document.querySelector('.row').innerHTML=`<span>👑 ${d[0].name}</span><span style="color:#ff6a00">${d[0].score} XP</span>`}}catch{}};loadLB();setInterval(loadLB,5000);
document.querySelector('.fire').onclick=async()=>{let v=document.getElementById('cmd').value;if(!v)return;let fd=new FormData();document.querySelector('.chat-box').innerHTML+=`<br><br><div style="text-align:right;color:#fff">You: ${v}</div>`;fetch('/api/save-score',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'Sparsh Singhal [YOU]',score:Math.floor(Math.random()*100)})});document.getElementById('cmd').value='';}
</script></body></html>
"""

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve(path):
    if path and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    if os.path.exists(os.path.join(app.static_folder, "index.html")):
        return send_from_directory(app.static_folder, "index.html")
    return ORIGINAL_HTML

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
