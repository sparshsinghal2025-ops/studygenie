from flask import Flask, jsonify
import os

app = Flask(__name__)

@app.route("/api/admin_users")
@app.route("/admin_users")
def admin_users():
    redis_url = os.environ.get("REDIS_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
    return jsonify({
        "status": "API IS WORKING",
        "redis": "ON" if redis_url else "OFF",
        "redis_url_set": bool(redis_url)
    })

@app.route("/")
@app.route("/<path:path>")
def home(path=""):
    return "studygenie.ai - API working, now connect main app"
