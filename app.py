from flask import Flask, request, jsonify
import os

app = Flask(__name__)

def get_ai(topic):
    key = os.getenv("GEMINI_KEY")
    if not key:
        return "GEMINI_KEY Vercel me nahi hai"
    try:
        from google import genai
        client = genai.Client(api_key=key)
        r = client.models.generate_content(model="gemini-1.5-flash", contents=f"Explain {topic} in Hinglish, 5 points, 1 example")
        return r.text
    except Exception as e:
        return f"Error: {e}"

@app.route("/")
def home():
    return """
<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>StudyGenie</title>
<style>body{background:#000;color:#fff;font-family:system-ui;text-align:center;padding:20px}input{width:90%;max-width:500px;padding:14px;border-radius:12px;border:none}button{padding:12px 20px;margin:6px;border-radius:20px;border:none;font-weight:bold} .card{background:#111;padding:15px;border-radius:12px;max-width:600px;margin:20px auto;text-align:left;white-space:pre-wrap;border:1px solid #222}</style>
</head><body>
<h1>StudyGenie 🔥</h1><p>By Sparsh Singhal</p>
<input id="t" placeholder="Topic likho e.g. OOPS"><br><br>
<button onclick="ask()">Ask AI</button>
<div id="a" class="card">Ready hai!</div>
<script>
function ask(){
 let t=document.getElementById('t').value;
 if(!t){alert('Topic likh');return}
 a.innerText='Soch raha hu...';
 fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({topic:t})})
 .then(r=>r.json()).then(d=>a.innerText=d.reply)
}
</script>
</body></html>
"""

@app.route("/api/ask", methods=["POST"])
def ask_api():
    d = request.get_json() or {}
    return jsonify({"reply": get_ai(d.get("topic","DBMS"))})

@app.route("/health")
def h(): return "OK"
