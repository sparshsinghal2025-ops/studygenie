from flask import Flask
app = Flask(__name__)

HTML = """
<!DOCTYPE html><html><head><title>StudyGenie by Sparsh</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font-family:system-ui;background:#0f0f0f;color:#fff;text-align:center;padding:30px}
input{padding:16px;width:85%;max-width:420px;border-radius:12px;border:none;font-size:18px;margin-top:10px}
button{padding:13px 22px;margin:8px;border-radius:10px;border:none;background:#a855f7;color:#fff;font-weight:bold;cursor:pointer;font-size:15px}
#out{margin-top:28px;text-align:left;background:#1e1e1e;padding:20px;border-radius:14px;max-width:620px;margin-left:auto;margin-right:auto;white-space:pre-wrap;line-height:1.6}</style>
</head><body>
<h1>🧞 StudyGenie</h1><p>by Sparsh Singhal - 1min me koi bhi topic samjho</p>
<input id="q" placeholder="Ex: Photosynthesis, Linked List, Relativity">
<br><button onclick="gen(1)">1 Min Quick</button><button onclick="gen(5)">5 Min Deep</button><button onclick="gen(10)">10 Min Master</button>
<div id="out">Yaha magic ayega... Topic likho upar 👆</div>
<script>
function gen(m){
let t=document.getElementById('q').value; if(!t) return alert('Bhai topic toh likh!');
document.getElementById('out').innerHTML=`<b>🧞 ${t} - ${m} Min Summary</b><br><br>`+
`✅ <b>Definition:</b> ${t} ka simple matlab...<br><br>`+
`✅ <b>Example:</b> Real life me ${t} aise kaam karta hai...<br><br>`+
`✅ <b>Trick to Remember:</b> ${t} = Short trick<br><br>`+
`🔥 <b>Phase 1 LIVE Hai!</b> Agle phase me AI API connect karenge!`;
}
</script></body></html>
"""

@app.route('/')
def home(): return HTML
@app.route('/<path:path>')
def catch_all(path): return HTML
