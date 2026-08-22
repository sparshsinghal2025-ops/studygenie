from flask import Flask, request, jsonify
import google.generativeai as genai, os

app = Flask(__name__)
genai.configure(api_key=os.getenv("GEMINI_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')

BRANDING = "\n\n---\nMade with ❤️ by StudyGenie by Sparsh Singhal"
LANGUAGES = {"hindi": "Hindi", "english": "English", "hinglish": "Hinglish", "tamil": "Tamil", "bengali": "Bengali", "telugu": "Telugu", "marathi": "Marathi", "gujarati": "Gujarati", "kannada": "Kannada", "malayalam": "Malayalam", "punjabi": "Punjabi", "odia": "Odia"}
USERS = {}

def get_user(p):
    if p not in USERS: USERS[p] = {"xp":0, "bhasha":"hindi", "mode":"free", "msg_count":0}
    return USERS[p]

@app.route("/webhook", methods=["POST"])
def webhook():
    d=request.get_json()
    p=d.get("from","test")
    msg=d.get("message","hi")
    u=get_user(p)
    lang=LANGUAGES.get(u["bhasha"], "Hindi")

    if u["mode"]=="free" and u["msg_count"]>=15:
        return jsonify({"reply":f"🚫 FREE limit khatam! ULTRA ₹49 jaldi aayega - Unlimited ban jayega{BRANDING}"})

    if msg.lower()=="/help":
        r=f"StudyGenie by Sparsh Singhal\n\nCommands:\n/1min [topic] - 1 min me samjhao\n/xp - apna level dekho\n/bhasha [hindi/english] - bhasha badlo\n/mood\n\nFree: 15 msg/day{BRANDING}"
    elif msg.lower().startswith("/bhasha"):
        try:
            new_lang=msg.split()[1].lower()
            u["bhasha"]=new_lang
            r=f"Bhasha badal gayi: {LANGUAGES.get(new_lang, new_lang)}{BRANDING}"
        except:
            r=f"Bhasha use: /bhasha hindi{BRANDING}"
    elif msg.lower()=="/xp":
        lvl=u["xp"]//100+1
        r=f"Level {lvl} | XP: {u['xp']}/{lvl*100} 🚀\nMode: {u['mode']}{BRANDING}"
    elif msg.lower().startswith("/1min"):
        topic=msg[6:] if len(msg)>5 else "general topic"
        res=model.generate_content(f"You are StudyGenie by Sparsh Singhal. Explain {topic} in {lang} in 3 lines + 1 trick + 1 example. Be a friendly bhai.")
        r=res.text+BRANDING
        u["msg_count"]+=1
        u["xp"]+=10
    else:
        res=model.generate_content(f"You are StudyGenie by Sparsh Singhal, Indian Bhai. Answer '{msg}' in {lang}. Short, motivating, with example.")
        r=res.text+BRANDING
        u["msg_count"]+=1
        u["xp"]+=10
    return jsonify({"reply":r})

@app.route("/", methods=["GET"])
def home():
    return "Study Genie by Sparsh Singhal V1.0 LIVE"
