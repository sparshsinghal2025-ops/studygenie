import os
from flask import Flask, request, jsonify, send_from_directory, render_template_string
import google.generativeai as genai

app = Flask(__name__)

# --- Gemini Setup ---
API_KEY = os.environ.get("GOOGLE_API_KEY", "")
if API_KEY:
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel("gemini-1.5-flash")
else:
    model = None

HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>StudyGenie by Sparsh Singhal</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>body{background:#1e1b4b; color:white;}</style>
</head>
<body class="p-3">
<div class="flex justify-between items-center mb-4">
  <div class="flex items-center gap-3">
    <img src="/sparsh.jpg" class="w-14 h-14 rounded-full border-2 border-orange-500 object-cover" alt="Sparsh">
    <div>
      <h1 class="text-xl font-black">StudyGenie <span class="text-orange-400">by Sparsh Singhal</span></h1>
      <p class="text-xs opacity-70">Genie Bolega Ab</p>
    </div>
  </div>
  <div class="flex gap-2 text-xs">
    <span class="bg-white/10 px-3 py-1 rounded-full">1 live</span>
    <span class="bg-orange-500/20 border border-orange-500 px-3 py-1 rounded-full">1 streak</span>
  </div>
</div>

<div class="grid grid-cols-1 md:grid-cols-4 gap-3">
  <div class="md:col-span-3 bg-white/10 rounded-2xl p-4 min-h-[60vh]">
    <div id="chat" class="space-y-3">
      <div class="bg-white/20 p-3 rounded-2xl">Hukm mere aaka! Mai Sparsh Singhal ka Genie hu, bolo kya seekhna hai?</div>
    </div>
    <div class="mt-4 flex gap-2">
      <input id="q" class="flex-1 bg-white/10 rounded-full px-4 py-2 outline-none" placeholder="Pucho...">
      <button onclick="ask()" class="bg-orange-500 px-6 py-2 rounded-full font-bold">GO</button>
    </div>
    <div class="mt-3 w-full bg-black/30 h-2 rounded-full"><div class="bg-yellow-300 h-2 rounded-full" style="width:84%"></div></div>
    <p class="text-xs mt-1">Level 1 - 84 XP</p>
  </div>

  <div class="space-y-3">
    <div class="bg-white/10 p-4 rounded-2xl"><h3 class="font-bold">Wishes <span class="text-orange-400">Unlimited</span> <span class="text-[10px] border px-2 rounded-full">DEV UNLIMITED</span></h3><div class="h-1 bg-orange-500 mt-2"></div><p class="text-xs mt-2 opacity-70">Only you is grinding</p></div>
    <div class="bg-white/10 p-4 rounded-2xl"><p>Battery -</p></div>
    <div class="bg-white/10 p-4 rounded-2xl"><p class="font-bold">Leaderboard #1</p><p class="text-xs">You - 84 XP</p></div>
  </div>
</div>

<script>
async function ask(){
  let q = document.getElementById('q').value;
  if(!q) return;
  let chat = document.getElementById('chat');
  chat.innerHTML += `<div class="bg-orange-500 p-3 rounded-2xl ml-10">${q}</div>`;
  document.getElementById('q').value='';
  let res = await fetch('/ask', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({q})});
  let data = await res.json();
  chat.innerHTML += `<div class="bg-white/20 p-3 rounded-2xl mr-10">${data.ans}</div>`;
}
</script>
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HTML)

# --- Photo Fix: root + static dono se serve karega ---
@app.route("/sparsh.jpg")
def sparsh_root():
    try:
        return send_from_directory("static", "sparsh.jpg")
    except:
        return send_from_directory(".", "sparsh.jpg")

@app.route("/static/<path:p>")
def static_files(p):
    try:
        return send_from_directory("static", p)
    except:
        return send_from_directory(".", p)

@app.route("/ask", methods=["POST"])
def ask():
    q = request.json.get("q","")
    if not model:
        return jsonify({"ans": "API Key missing on Vercel. Add GOOGLE_API_KEY in env."})
    try:
        resp = model.generate_content(f"You are StudyGenie by Sparsh Singhal. Answer in Hinglish, friendly: {q}")
        return jsonify({"ans": resp.text})
    except Exception as e:
        return jsonify({"ans": f"Error: {str(e)}"})

if __name__ == "__main__":
    app.run()
